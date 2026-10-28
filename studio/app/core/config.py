import logging
import os
from functools import lru_cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

AppEnv = Literal["dev", "sit", "prod"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def get_app_version() -> str:
    try:
        return pkg_version("studio")
    except PackageNotFoundError:
        return "0.0.0"


_STUDIO_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    app_env: AppEnv = "dev"
    app_debug: bool = True
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    # 只影响 root logger 的级别(见 app/core/logging.py); 取值必须是大写字面量之一
    log_level: LogLevel = "INFO"

    db_host: str = "localhost"
    db_port: int = 3306
    db_name: str = ""
    db_user: str = ""
    db_password: str = ""
    db_pool_size: int = Field(5, ge=1)
    db_max_overflow: int = Field(10, ge=0)
    db_echo: bool = False

    # 导出目录。产物是【两个文件】——与 studio/schema/*.data.jsonc 的顶层数组一致:
    #   topics-{env}.json / tools-{env}.json;prod 额外同步一份无后缀的 topics.json / tools.json
    export_output_dir: str = "../web/data"

    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    api_key: str = "dev-secret-key"

    # ── AI 评分管线(app/scoring,离线跑;服务进程本身不调用模型) ──────────────
    # 刻意不进服务启动校验:没有 key 也要能正常起服务、跑测试。真正需要它的是
    # `python -m app.scoring`,由那边在开跑前检查并给出可读报错。
    #
    # 调用方式:DeepSeek 的 Responses API(不是老的 /chat/completions)。
    # 模型名必须用 `deepseek-flash`:旧的 deepseek-chat / deepseek-reasoner 已在
    # 2026-07-24 下线,写旧名会直接 404。base_url 官方写法不带 /v1。
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-flash"
    # 带单位后缀:同一个"超时"在别处是秒还是毫秒不该靠猜
    llm_timeout_seconds: float = Field(60.0, gt=0)
    llm_max_retries: int = Field(2, ge=0, le=5)
    llm_max_output_tokens: int = Field(4000, ge=256)
    # 思考模式默认开启(DeepSeek 侧默认 effort=high)。评分是批处理,low 更省钱也够用;
    # 注意:思考模式下 temperature 被忽略,所以本配置里【没有】temperature。
    llm_reasoning_effort: Literal["low", "high", "max"] = "low"
    # json_schema: 解码层就约束成我们定义的 JSON Schema(首选);
    # json_object: 只保证合法 JSON,字段靠 prompt + Pydantic 兜底(provider 不支持 schema 时降级)
    llm_structured_output: Literal["json_schema", "json_object"] = "json_schema"

    # 单个工具采样几次。N>1 是为了拿"采样一致率"当置信度,并给维度分取中位数;
    # 调到 1 会退化成单次裸分(不推荐,见 app/scoring/aggregate.py 的说明)。
    scoring_samples: int = Field(3, ge=1, le=9)
    scoring_concurrency: int = Field(4, ge=1, le=32)
    # 权威度在最终分里的占比:final = (1-gamma)·quality + gamma·authority。
    # 改这个值会让 ai_score_version 变化,旧分数要靠 --outdated-version 重算。
    scoring_authority_weight: float = Field(0.50, ge=0, le=1)
    # 超过这么多天的分数视为过期(--stale-days 的默认值)
    scoring_stale_days: int = Field(90, ge=1)

    model_config = SettingsConfigDict(
        env_file=str(_STUDIO_ROOT / f".env.{os.getenv('APP_ENV', 'dev')}"),
        env_file_encoding="utf-8",
    )

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, v: Any) -> Any:
        # LOG_LEVEL=info 是最顺手的写法, 但 Literal 只做精确匹配, 这里统一成大写
        return v.upper() if isinstance(v, str) else v

    @field_validator("db_host", "db_name", "db_user")
    @classmethod
    def validate_db_identity(cls, v: str, info: ValidationInfo) -> str:
        # 这三个键空着不会在启动时报错, 而是等到第一次查询才炸出 aiomysql 的原始
        # 错误("No database selected" / "Access denied"), 排查成本高得多。
        # db_password 刻意不校验: 本地库允许空密码, 那是合法配置。
        if not v.strip():
            raise ValueError(f"{info.field_name} 不能为空(在 .env.<APP_ENV> 里配置)")
        return v.strip()

    @field_validator("app_debug")
    @classmethod
    def validate_app_debug(cls, v: bool, info: ValidationInfo) -> bool:
        env = info.data.get("app_env", "dev")
        if env != "dev" and v:
            raise ValueError(
                f"app_debug 只能在 dev 打开(当前 APP_ENV={env}): debug 会让 Starlette 短路全局"
                " 500 处理器 —— 未鉴权请求即可拿到含源码片段的 traceback, 且丢掉 X-Request-ID"
            )
        return v

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str, info: ValidationInfo) -> str:
        env = info.data.get("app_env", "dev")
        if not v:
            raise ValueError(f"api_key must not be empty (configure API_KEY in .env.{env})")
        if env != "dev" and v == "dev-secret-key":
            raise ValueError(
                f"api_key must be set to a non-default value in {env} environment (configure API_KEY in .env.{env})"
            )
        return v

    @field_validator("export_output_dir")
    @classmethod
    def validate_export_output_dir(cls, v: str) -> str:
        # 空串会被 Path("") 解析成"."(studio/ 本身), 产物静默落到源码目录里, 必须拦下
        if not v.strip():
            raise ValueError("export_output_dir 不能为空(默认 ../web/data)")
        return v.strip()

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, v: str) -> str:
        # main.py 里 allow_credentials=True 是写死的。Starlette 在这个组合下遇到 "*" 会把
        # 请求的 Origin 原样回显,等于对任意站点开放凭证;现在只用 X-API-Key(不是浏览器
        # 自动携带的凭证)所以风险有限,但哪天加了 Cookie 会话就是真漏洞。宁可启动失败。
        origins = [origin.strip() for origin in v.split(",") if origin.strip()]
        if "*" in origins:
            raise ValueError("cors_origins 不能用 *(allow_credentials=True 下会回显任意 Origin), 请逐个列白名单")
        # 空值同样是坑: CORS_ORIGINS= 不会报错, 只是浏览器请求全被挡下, 前端只看到
        # 一个没有细节的 CORS 错误。.env.example 写明这是必填项, 这里兑现它。
        if not origins:
            raise ValueError("cors_origins 不能为空(如 http://localhost:3000, 多个用逗号分隔)")
        return v

    @property
    def database_url(self) -> str:
        return (
            f"mysql+aiomysql://{quote(self.db_user, safe='')}:{quote(self.db_password, safe='')}"
            f"@{self.db_host}:{self.db_port}/{quote(self.db_name, safe='')}?charset=utf8mb4"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def export_dir(self) -> Path:
        """导出目录(绝对路径)。

        相对路径按 studio/ 解析而不是进程 cwd —— 产物落在哪儿不该取决于谁在哪个目录下
        敲的命令;resolve() 只是把 studio/../web/data 里的 ".." 折掉, 让日志与
        ExportResponse.output_path 里的路径可读。
        """
        path = Path(self.export_output_dir)
        return (path if path.is_absolute() else _STUDIO_ROOT / path).resolve()

    def export_paths(self, *, frontend_names: bool = False) -> dict[str, Path]:
        """导出产物路径。

        frontend_names=True 时用无环境后缀的名字(topics.json / tools.json),
        只在 prod 下额外同步——开发产物带 -dev/-sit 后缀,避免误覆盖前端数据源。
        """
        suffix = "" if frontend_names else f"-{self.app_env}"
        directory = self.export_dir
        return {
            "topics": directory / f"topics{suffix}.json",
            "tools": directory / f"tools{suffix}.json",
        }


@lru_cache
def get_settings() -> Settings:
    value = Settings()
    env_file = _STUDIO_ROOT / f".env.{value.app_env}"
    if not env_file.exists():
        logger.warning("Env file not found: %s (falling back to env vars/defaults)", env_file)
    return value
