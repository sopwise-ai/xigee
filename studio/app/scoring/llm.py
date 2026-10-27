"""OpenAI 兼容的 judge 客户端 + 严格的结构化输出解析。

为什么不用官方 SDK:DeepSeek / OpenAI / 自建 vLLM 都实现了同一套
`POST {base_url}/chat/completions`,一个 httpx 客户端就能全覆盖,不必为一个离线
批处理脚本引入三家 SDK(也确实不需要流式、function calling)。

解析策略是"宽进严出":
- 宽进:模型偶尔会把 JSON 包进 ```json 围栏,或者前后带一句客套话,先尽力取出对象;
- 严出:取出来的对象必须通过 Judgement 校验(5 个维度齐全、分数 1~5、slug 是字符串)。
  校验不过【不静默修补】: 这次采样记为失败, 整条工具在下次运行时会因为
  ai_score_at 仍为空而被重新捡起来。给缺的维度补 3 分是最糟的做法 —— 那等于把
  模型没给出的判断塞进 ai_score, 事后无法区分哪些分是"猜"的。
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.scoring.rubric import DIMENSION_KEYS

logger = logging.getLogger(__name__)

# 这些状态码值得重试:限流、网关抖动、上游过载。4xx 里的其余(401/403/404/422)
# 重试只会把同一个错误再打一遍,直接失败更快暴露配置问题。
_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

MAX_RETRIES = 2
_BACKOFF_BASE_SECONDS = 0.8


class JudgeError(RuntimeError):
    """模型调用或输出解析失败(重试之后)。"""


class TopicChoice(BaseModel):
    slug: str = Field(min_length=1, max_length=64)
    confidence: float = Field(0.5, ge=0.0, le=1.0)


class DimensionJudgement(BaseModel):
    score: int = Field(ge=1, le=5)
    reason: str = ""

    model_config = {"extra": "ignore"}


class Judgement(BaseModel):
    """一次采样的结构化结果。维度必须齐全且不能有多余 key。"""

    topics: list[TopicChoice] = Field(default_factory=list, max_length=3)
    dimensions: dict[str, DimensionJudgement]
    summary: str = ""

    model_config = {"extra": "ignore"}

    @model_validator(mode="after")
    def check_dimensions(self) -> Judgement:
        missing = set(DIMENSION_KEYS) - set(self.dimensions)
        unknown = set(self.dimensions) - set(DIMENSION_KEYS)
        if missing or unknown:
            raise ValueError(f"维度不匹配: 缺少 {sorted(missing)}, 多出 {sorted(unknown)}")
        return self

    def scores(self) -> dict[str, int]:
        return {key: value.score for key, value in self.dimensions.items()}


def parse_judgement(content: str) -> Judgement:
    """从模型返回的文本里取出 Judgement。

    只做"取对象 + 校验",不做任何猜测性修补(比如给缺的维度补 3 分)——那会让
    ai_score 里混进模型根本没给出的判断,而且事后无法区分。
    """
    text = (content or "").strip()
    if not text:
        raise ValueError("模型返回空内容")

    # 去掉 ```json ... ``` / ``` ... ``` 围栏(只处理首尾,不动中间的合法内容)
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    # 兜底:模型在 JSON 前后说了话。取第一个 { 到最后一个 },比正向解析宽容、
    # 又不会把两个对象拼在一起(那种情况 json.loads 会直接失败,交给重试)。
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        text = text[start : end + 1]

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"输出不是合法 JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"输出必须是 JSON 对象,实际是 {type(payload).__name__}")

    try:
        return Judgement.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"输出结构不合法: {exc}") from exc


class Judge(Protocol):
    """判分器接口。测试里用假实现替换,不碰网络。"""

    async def complete(self, *, system: str, user: str) -> str: ...


class OpenAICompatJudge:
    """OpenAI 兼容的 chat/completions 客户端。

    并发安全:pipeline 会用同一个实例发多个请求,httpx.AsyncClient 本身支持并发。
    因此这里只创建一个 client,由调用方在结束时 `await judge.aclose()`。
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 60.0,
        temperature: float = 0.2,
    ) -> None:
        if not api_key:
            raise ValueError("LLM_API_KEY 未配置,无法调用模型")
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._api_key = api_key
        self._model = model
        self._temperature = temperature
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def complete(self, *, system: str, user: str) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "temperature": self._temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # 让服务端保证是 JSON 对象;解析端仍然会再校验一遍结构
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            if attempt:
                # 指数退避 + 抖动:并发批量跑时,同时失败的重试不要继续同时打到上游
                delay = _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)) * (0.5 + random.random())  # noqa: S311 —— 退避抖动,不需要密码学随机
                await asyncio.sleep(delay)
            try:
                response = await self._client.post(self._url, json=payload, headers=headers)
            except httpx.RequestError as exc:
                last_error = JudgeError(f"请求失败: {exc}")
                logger.warning("judge 请求失败(第 %d 次): %s", attempt + 1, exc)
                continue

            if response.status_code in _RETRYABLE_STATUS:
                last_error = JudgeError(f"上游 {response.status_code}: {response.text[:300]}")
                logger.warning("judge 可重试错误(第 %d 次): HTTP %s", attempt + 1, response.status_code)
                continue
            if response.status_code >= 400:
                # 不可重试:认证 / 模型名 / 参数错误,重试只是浪费时间
                raise JudgeError(f"上游 {response.status_code}: {response.text[:300]}")

            try:
                body = response.json()
                content = body["choices"][0]["message"]["content"]
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("content 为空")
                return content
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                last_error = JudgeError(f"响应结构异常: {exc}")
                logger.warning("judge 响应结构异常(第 %d 次): %s", attempt + 1, exc)

        raise JudgeError(f"重试 {MAX_RETRIES} 次后仍失败: {last_error}")
