"""DeepSeek judge 客户端(Responses API) + 严格的结构化输出解析。

为什么是 Responses API 而不是 /chat/completions:
  1. DeepSeek 的 Responses API 原生支持 `text.format`,可以传完整的 JSON Schema,
     模型在解码层就被约束成我们要的结构 —— 缺维度、分数越界、凭空发明 slug
     这类错误从"事后校验"前移成"根本生成不出来";
  2. `reasoning.effort` 可以显式控制思考强度,批处理用 low 就够了;
  3. 旧接口里 temperature 在思考模式下是无效参数,继续传只是自欺欺人,这里干脆不传。

解析策略是"宽进严出":
- 宽进:模型偶尔会把 JSON 包进 ```json 围栏,或者前后带一句客套话,先尽力取出对象;
- 严出:取出来的对象必须通过 Judgement 校验(维度齐全、分数在值域内、authority 存在)。
  校验不过【不静默修补】:这次采样记为失败,整条工具在下次运行时会因为 ai_score_at
  没更新而被重新捡起来。给缺的维度补 3 分是最糟的做法 —— 那等于把模型没给出的判断
  塞进 ai_score,事后无法区分哪些分是"猜"的。
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.scoring.rubric import DIMENSION_KEYS, MAX_AUTHORITY, MIN_AUTHORITY

logger = logging.getLogger(__name__)

# 这些状态码值得重试:限流、网关抖动、上游过载。其余 4xx(401/403/404/422)
# 重试只会把同一个错误再打一遍,直接失败更快暴露配置问题。
_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

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


class AuthorityJudgement(BaseModel):
    """行业权威度:0~9,越高越"重要"。它不是质量分,见 rubric 的说明。"""

    score: int = Field(ge=MIN_AUTHORITY, le=MAX_AUTHORITY)
    reason: str = ""

    model_config = {"extra": "ignore"}


class Judgement(BaseModel):
    """一次采样的结构化结果。维度必须齐全且不能有多余 key。"""

    topics: list[TopicChoice] = Field(default_factory=list, max_length=3)
    dimensions: dict[str, DimensionJudgement]
    authority: AuthorityJudgement
    summary: str = ""

    model_config = {"extra": "ignore"}

    @field_validator("dimensions", mode="before")
    @classmethod
    def drop_unknown_dimensions(cls, value: object) -> object:
        """先丢掉多余键,再做逐项校验。

        顺序很关键:如果等到 after-validator 才处理,`dimensions_note: null` 会先在
        dict[str, DimensionJudgement] 的逐项校验里炸掉 —— 我们连"它只是注脚"都来不及判断。
        """
        if isinstance(value, dict):
            return {key: item for key, item in value.items() if key in DIMENSION_KEYS}
        return value

    @model_validator(mode="after")
    def check_dimensions(self) -> Judgement:
        # 已知维度必须齐全 —— 缺一个就说明这次采样不可用。
        # 多余键直接丢掉(实测模型会塞 dimensions_note 这类注脚):它们是"多余信息",
        # 不是"补出来的分数",丢掉不会伪造任何判断。
        missing = set(DIMENSION_KEYS) - set(self.dimensions)
        if missing:
            raise ValueError(f"维度缺失: {sorted(missing)}")
        self.dimensions = {key: self.dimensions[key] for key in DIMENSION_KEYS}
        return self

    def scores(self) -> dict[str, int]:
        return {key: value.score for key, value in self.dimensions.items()}


def judgement_json_schema() -> dict[str, Any]:
    """给 `text.format` 用的严格 Schema。

    刻意只用结构化输出支持的少量关键字(type/properties/required/
    additionalProperties/items/enum/maxItems):`minimum`/`maximum` 这类约束在
    strict 模式下可能被上游拒绝,所以值域用 enum 表达。Pydantic 仍然是第二道闸。
    """
    dimension_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "score": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
            "reason": {"type": "string"},
        },
        "required": ["score", "reason"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "topics": {
                "type": "array",
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "slug": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["slug", "confidence"],
                    "additionalProperties": False,
                },
            },
            "dimensions": {
                "type": "object",
                "properties": dict.fromkeys(DIMENSION_KEYS, dimension_schema),
                "required": list(DIMENSION_KEYS),
                "additionalProperties": False,
            },
            "authority": {
                "type": "object",
                "properties": {
                    "score": {"type": "integer", "enum": list(range(MIN_AUTHORITY, MAX_AUTHORITY + 1))},
                    "reason": {"type": "string"},
                },
                "required": ["score", "reason"],
                "additionalProperties": False,
            },
            "summary": {"type": "string"},
        },
        "required": ["topics", "dimensions", "authority", "summary"],
        "additionalProperties": False,
    }


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
    """DeepSeek Responses API 客户端。

    并发安全:pipeline 会用同一个实例发多个请求,httpx.AsyncClient 本身支持并发。
    因此这里只创建一个 client,由调用方在结束时 `await judge.aclose()`。
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        max_output_tokens: int = 2000,
        reasoning_effort: str = "low",
        structured_output: str = "json_schema",
    ) -> None:
        if not api_key:
            raise ValueError("LLM_API_KEY 未配置,无法调用模型")
        self._endpoint = f"{base_url.rstrip('/')}/responses"
        self._api_key = api_key
        self._model = model
        self._max_retries = max_retries
        self._max_output_tokens = max_output_tokens
        self._reasoning_effort = reasoning_effort
        # 运行期可能从 json_schema 降级到 json_object(见 complete 的 400 分支)
        self._format_type = structured_output
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))

    async def aclose(self) -> None:
        await self._client.aclose()

    def _build_payload(self, system: str, user: str) -> dict[str, Any]:
        if self._format_type == "json_schema":
            text_format: dict[str, Any] = {
                "type": "json_schema",
                "name": "tool_judgement",
                "strict": True,
                "schema": judgement_json_schema(),
            }
        else:
            text_format = {"type": "json_object"}
        return {
            "model": self._model,
            "instructions": system,
            "input": user,
            "reasoning": {"effort": self._reasoning_effort},
            "text": {"format": text_format},
            "max_output_tokens": self._max_output_tokens,
        }

    @staticmethod
    def _extract_text(body: dict[str, Any]) -> str:
        """从 Responses API 的 response 对象里取正文。

        结构是 output[] → 取 type=message 的项 → content[] → 取 type=output_text 的 part。
        SDK 会额外给出顶层 output_text,原生 HTTP 响应不一定有,所以两条路都走。
        """
        status = body.get("status")
        if status == "failed":
            raise ValueError(f"response.failed: {body.get('error')}")
        # 截断(通常是 max_output_tokens 被思考 token 吃掉)绝不能把半截 JSON 当结果:
        # 它会在 parse 阶段报一个看不出根因的 JSONDecodeError,而真正的原因是预算不够。
        if status == "incomplete":
            raise ValueError(f"response.incomplete: {body.get('incomplete_details')}")

        direct = body.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct

        chunks: list[str] = []
        for item in body.get("output") or []:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for part in item.get("content") or []:
                if isinstance(part, dict) and part.get("type") == "output_text" and isinstance(part.get("text"), str):
                    chunks.append(part["text"])

        text = "".join(chunks).strip()
        if not text:
            raise ValueError("响应里没有 output_text")
        if usage := body.get("usage"):
            logger.debug("judge usage: %s", usage)
        return text

    async def complete(self, *, system: str, user: str) -> str:
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        last_error: Exception | None = None
        attempt = 0

        while attempt <= self._max_retries:
            if attempt:
                # 指数退避 + 抖动:并发批量跑时,同时失败的重试不要继续同时打到上游
                delay = _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)) * (0.5 + random.random())  # noqa: S311
                await asyncio.sleep(delay)

            try:
                response = await self._client.post(
                    self._endpoint, json=self._build_payload(system, user), headers=headers
                )
            except httpx.RequestError as exc:
                last_error = JudgeError(f"请求失败: {exc}")
                logger.warning("judge 请求失败(第 %d 次): %s", attempt + 1, exc)
                attempt += 1
                continue

            # 上游不认 json_schema 时降级一次。不消耗重试次数,也不睡眠 ——
            # 这是能力协商,不是网络抖动。
            if response.status_code == 400 and self._format_type == "json_schema":
                logger.warning("json_schema 被拒绝,降级为 json_object: %s", response.text[:200])
                self._format_type = "json_object"
                continue

            if response.status_code in _RETRYABLE_STATUS:
                last_error = JudgeError(f"上游 {response.status_code}: {response.text[:300]}")
                logger.warning("judge 可重试错误(第 %d 次): HTTP %s", attempt + 1, response.status_code)
                attempt += 1
                continue
            if response.status_code >= 400:
                raise JudgeError(f"上游 {response.status_code}: {response.text[:300]}")

            try:
                return self._extract_text(response.json())
            except (ValueError, TypeError) as exc:
                last_error = JudgeError(f"响应结构异常: {exc}")
                logger.warning("judge 响应结构异常(第 %d 次): %s", attempt + 1, exc)
                attempt += 1

        raise JudgeError(f"重试 {self._max_retries} 次后仍失败: {last_error}")
