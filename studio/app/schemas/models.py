"""请求/响应 Schema。

职责边界(和 schema.sql 的分工):
  - schema.sql 已经退化成"只做存储":没有 CHECK,没有 ENUM。值域(枚举取值)与集合
    约束(标签去重、语言码格式、url 允不允许 http)【只能】在这里拦,拦不住就直接落库
  - 这里做【写入端】校验,把坏数据拦在 422,而不是让它撞库报 500
  - 库里还留着的 NOT NULL / UNIQUE / VARCHAR 长度在这里重复一份是有意的:报错信息更友好

枚举一律用 app.models 里的 StrEnum,值即 schema.sql 列注释里的字符串。
"""

from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models import Access, LinkLabel, LinkStatus, Origin, Pricing, ToolStatus, TopicStatus
from app.utils.url import LOCAL_HOSTS

_SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
MAX_TAGS = 8
MAX_LANGUAGES = 8
MAX_TAG_LENGTH = 32
# 与 xg_tool_link.url 的 VARCHAR(2048) 是同一个上限: 归一化后还会再校验一次
# (长 URL 百分号编码会膨胀), 两处必须同值
MAX_URL_LENGTH = 2048
# 卡片文案上限。中文习惯 21~47 字; 同样信息量的英文约为中文的 2 倍字符, 现有最长文案
# (47 字) 的英文版约 95 字符, 所以 100 刚好覆盖且仍在一张卡片两行(line-clamp-2)的显示容量内。
MAX_TAGLINE_LENGTH = 100
# AI 评分的值域(与 schema.sql 的 SMALLINT/0~1000 口径一致)。派生列本身不由 API
# 写入,这里只用于人工复核分 review_score —— 它与 ai_score 同一把尺子,才好校准。
MAX_AI_SCORE = 1000
_LANG_CODE_LENGTH = 2


def _check_name(value: str) -> str:
    """显示名不能为空或纯空白, 返回去掉首尾空白后的值。

    库层是 VARCHAR NOT NULL —— 空串是合法值, 能 201 落库; 而导出端把空 slug/name
    的行【静默跳过】(见 json_exporter._invalid_reason)。不拦的话就能建出一个
    "永远不上站"的工具/主题, 唯一线索只有导出响应里的 skipped_count。
    min_length=1 挡不住 "  ", 所以必须 strip 后判空。
    """
    if not value.strip():
        raise ValueError("name 不能为空或纯空白")
    return value.strip()


def _check_url(value: str) -> str:
    """url 必须是 http(s),且非本地地址必须是 https(对齐归一化规则第 1 条)。

    本地地址白名单直接用 app.utils.url 的那一份:归一化在写入端做,这里和它必须
    认同同一批主机名,否则会出现"校验放行 http、归一化却把它改成 https"的静默改写。
    """
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("url 必须是 http(s) 开头")
    if parsed.scheme == "http" and parsed.hostname not in LOCAL_HOSTS:
        raise ValueError("url 必须是 https(只有 localhost/127.0.0.1 等本地地址可用 http)")
    if not parsed.hostname:
        raise ValueError("url 缺少主机名")
    return value


def _check_languages(value: list[str]) -> list[str]:
    """ISO 639-1:两字母小写。刻意不接受 zh-CN —— 要表达简/繁请用 tag。"""
    if not 1 <= len(value) <= MAX_LANGUAGES:
        raise ValueError(f"languages 需要 1~{MAX_LANGUAGES} 项")
    if len(set(value)) != len(value):
        raise ValueError("languages 不能重复")
    for code in value:
        # isalpha 而不是 islower 单独判: "z1" / "1z" 都满足 islower()+isascii()+len==2,
        # 但它们不是语言码(实测旧写法放行 z1)
        if not code.isascii() or not code.isalpha() or not code.islower() or len(code) != _LANG_CODE_LENGTH:
            raise ValueError(f"语言码必须是 ISO 639-1 两字母小写: {code!r}")
    return value


def _check_tags(value: list[str]) -> list[str]:
    if len(value) > MAX_TAGS:
        raise ValueError(f"tags 最多 {MAX_TAGS} 个")
    if len(set(value)) != len(value):
        raise ValueError("tags 不能重复")
    for tag in value:
        if not tag or tag != tag.strip():
            raise ValueError(f"标签首尾不能有空白且不能为空: {tag!r}")
        if len(tag) > MAX_TAG_LENGTH:
            raise ValueError(f"单个标签最长 {MAX_TAG_LENGTH} 字符: {tag!r}")
    return value


def _check_tagline(value: str) -> str:
    """句末必须是标点。

    库里【没有】ck_tool_tagline 这类 CHECK(schema.sql 已全部删除),所以这里是唯一的
    关卡:漏了它,导出物里的卡片文案就会长短不一。
    """
    if not value.strip():
        raise ValueError("tagline 不能为空白")
    if not value.rstrip().endswith(("。", ".", "\uff01", "!", "\uff1f", "?", "…")):
        raise ValueError("tagline 必须以标点结尾(库层不再校验,这里拦不住就进产物了)")
    return value


# ── 主题 ──────────────────────────────────────────────────────────────────────


class TopicBase(BaseModel):
    slug: str = Field(..., max_length=64, pattern=_SLUG_PATTERN)
    name: str = Field(..., min_length=1, max_length=64)
    icon: str = Field("📦", max_length=64)
    description: str | None = Field(None, max_length=500)
    sort_order: int = Field(0, ge=0)
    status: TopicStatus = TopicStatus.ACTIVE

    _validate_name = field_validator("name")(_check_name)


class TopicCreate(TopicBase):
    pass


class TopicUpdate(BaseModel):
    slug: str | None = Field(None, max_length=64, pattern=_SLUG_PATTERN)
    name: str | None = Field(None, min_length=1, max_length=64)
    icon: str | None = Field(None, max_length=64)
    description: str | None = Field(None, max_length=500)
    sort_order: int | None = Field(None, ge=0)
    status: TopicStatus | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        return None if v is None else _check_name(v)


class TopicResponse(TopicBase):
    id: int
    tool_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TopicCountResponse(BaseModel):
    tool_count: int


# ── 链接 ──────────────────────────────────────────────────────────────────────


class ToolLinkBase(BaseModel):
    url: str = Field(..., max_length=MAX_URL_LENGTH)
    label: LinkLabel = LinkLabel.OTHER
    is_primary: bool = False
    status: LinkStatus = LinkStatus.ACTIVE
    sort_order: int = Field(0, ge=0)

    _validate_url = field_validator("url")(_check_url)


class ToolLinkCreate(ToolLinkBase):
    pass


class ToolLinkUpdate(BaseModel):
    url: str | None = Field(None, max_length=MAX_URL_LENGTH)
    label: LinkLabel | None = None
    is_primary: bool | None = None
    status: LinkStatus | None = None
    sort_order: int | None = Field(None, ge=0)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str | None) -> str | None:
        return None if v is None else _check_url(v)


class ToolLinkResponse(ToolLinkBase):
    id: int
    tool_id: int
    last_link_check_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── 工具 ──────────────────────────────────────────────────────────────────────


class ToolBase(BaseModel):
    slug: str = Field(..., max_length=64, pattern=_SLUG_PATTERN)
    name: str = Field(..., min_length=1, max_length=128)
    tagline: str = Field(..., max_length=MAX_TAGLINE_LENGTH)
    description: str | None = Field(None, max_length=500)
    pricing: Pricing
    is_open_source: bool = False
    origin: Origin
    access: Access
    last_access_check_at: date | None = None
    languages: list[str]
    tags: list[str] = Field(default_factory=list)
    is_featured: bool = False
    status: ToolStatus = ToolStatus.DRAFT

    _validate_name = field_validator("name")(_check_name)
    _validate_tagline = field_validator("tagline")(_check_tagline)
    _validate_languages = field_validator("languages")(_check_languages)
    _validate_tags = field_validator("tags")(_check_tags)

    @field_validator("tags", mode="before")
    @classmethod
    def coerce_null_tags(cls, value: object) -> object:
        """tags 为 null 视同空数组。

        xg_tool.tags 是 JSON DEFAULT NULL(NULL 视同空数组)。导出格式要求 tags 恒为数组,
        而 ToolResponse 也继承本类:直连改库留下的 NULL 行如果不在这里折成 [],响应会整条
        校验失败(500),而不是少一个标签。
        """
        return [] if value is None else value


class ToolCreate(ToolBase):
    """建工具。主题用 topic_ids + primary_topic_id 表达主主题。"""

    topic_ids: list[int] = Field(default_factory=list)
    primary_topic_id: int | None = None
    links: list[ToolLinkCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_primary_topic(self) -> "ToolCreate":
        if self.primary_topic_id is not None and self.primary_topic_id not in self.topic_ids:
            raise ValueError("primary_topic_id 必须在 topic_ids 里")
        return self


class ToolUpdate(BaseModel):
    slug: str | None = Field(None, max_length=64, pattern=_SLUG_PATTERN)
    name: str | None = Field(None, min_length=1, max_length=128)
    tagline: str | None = Field(None, max_length=MAX_TAGLINE_LENGTH)
    description: str | None = Field(None, max_length=500)
    pricing: Pricing | None = None
    is_open_source: bool | None = None
    origin: Origin | None = None
    access: Access | None = None
    last_access_check_at: date | None = None
    languages: list[str] | None = None
    tags: list[str] | None = None
    is_featured: bool | None = None
    status: ToolStatus | None = None
    # ── 人工复核(唯一的可写入口;AI 字段不在任何输入 schema 里) ──────────────
    # review_score 传 null = 撤销复核(端点会把 reviewed_at/reviewed_by 一并清空);
    # 传值则端点自动补 reviewed_at 与 reviewed_by(缺省沿用原复核人)。
    review_score: int | None = Field(None, ge=0, le=MAX_AI_SCORE)
    reviewed_by: str | None = Field(None, max_length=64)
    topic_ids: list[int] | None = None
    primary_topic_id: int | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        return None if v is None else _check_name(v)

    @field_validator("tagline")
    @classmethod
    def validate_tagline(cls, v: str | None) -> str | None:
        return None if v is None else _check_tagline(v)

    @field_validator("languages")
    @classmethod
    def validate_languages(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _check_languages(v)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _check_tags(v)


class ToolResponse(ToolBase):
    id: int
    topic_ids: list[int] = Field(default_factory=list)
    primary_topic_id: int | None = None
    published_at: date | None
    created_at: datetime
    updated_at: datetime
    topics: list[TopicResponse] = Field(default_factory=list)
    links: list[ToolLinkResponse] = Field(default_factory=list)

    # AI 产出(只读;管理端可见,导出物里没有)。ai_score 是排序键,其余是审计/复核
    # 需要的上下文 —— 前端读的是 web/data/*.json 静态产物,看不到这些字段。
    ai_score: int = 0
    ai_score_confidence: float | None = None
    ai_score_version: str | None = None
    ai_score_at: datetime | None = None
    ai_topics: list[dict[str, Any]] | None = None
    # 人工复核(只读回显;写入口是 ToolUpdate 的 review_score)
    review_score: int | None = None
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None

    model_config = {"from_attributes": True}


class ToolTopicsUpdate(BaseModel):
    """只改工具的主题归属。primary_topic_id 省略时保留原有的主主题。"""

    topic_ids: list[int] = Field(default_factory=list)
    primary_topic_id: int | None = None

    @model_validator(mode="after")
    def check_primary_topic(self) -> "ToolTopicsUpdate":
        if self.primary_topic_id is not None and self.primary_topic_id not in self.topic_ids:
            raise ValueError("primary_topic_id 必须在 topic_ids 里")
        return self


class ToolTopicsResponse(BaseModel):
    """只改主题归属的响应。

    primary_topic_id 必须由端点回填【真实的主主题】(可能是"保留原有的"或"默认取第一个"),
    光看 topic_ids[0] 猜不出来 —— 让前端自己推断,主主题一旦被保留就看不出来了。
    """

    tool_id: int
    topic_ids: list[int]
    primary_topic_id: int | None = None
