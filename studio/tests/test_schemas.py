"""请求/响应模型的校验规则守卫。"""

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from app.schemas.models import (
    ToolCreate,
    ToolLinkCreate,
    ToolLinkUpdate,
    ToolTopicsUpdate,
    ToolUpdate,
    TopicCreate,
    TopicUpdate,
)

TOPIC_SLUG_MODELS: list[type[BaseModel]] = [TopicCreate, TopicUpdate]
SLUG_VALID = ["a", "chat-assistant", "topic-1", "zapier", "api"]
SLUG_INVALID = ["Chat", "chat assistant", "chat_assistant", "-chat", "chat-", "中文", ""]


def _tool_payload(**overrides: Any) -> dict[str, Any]:
    """ToolCreate 的合法底稿(必填字段一个都不能少)。"""
    payload: dict[str, Any] = {
        "slug": "tool",
        "name": "工具",
        "tagline": "一句话简介。",
        "pricing": "free",
        "origin": "cn",
        "access": "direct",
        "languages": ["zh"],
    }
    payload.update(overrides)
    return payload


# ── slug ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("model", TOPIC_SLUG_MODELS)
@pytest.mark.parametrize("slug", SLUG_VALID)
def test_topic_slug_accepts_url_friendly_values(model, slug):
    assert model(slug=slug, name="n").slug == slug


@pytest.mark.parametrize("model", TOPIC_SLUG_MODELS)
@pytest.mark.parametrize("slug", SLUG_INVALID)
def test_topic_slug_rejects_invalid_values(model, slug):
    with pytest.raises(ValidationError):
        model(slug=slug, name="n")


@pytest.mark.parametrize("slug", SLUG_VALID)
def test_tool_create_slug_accepts_url_friendly_values(slug):
    assert ToolCreate(**_tool_payload(slug=slug)).slug == slug


@pytest.mark.parametrize("slug", SLUG_INVALID)
def test_tool_create_slug_rejects_invalid_values(slug):
    with pytest.raises(ValidationError):
        ToolCreate(**_tool_payload(slug=slug))


@pytest.mark.parametrize("slug", SLUG_VALID)
def test_tool_update_slug_accepts_url_friendly_values(slug):
    assert ToolUpdate(slug=slug).slug == slug


@pytest.mark.parametrize("slug", SLUG_INVALID)
def test_tool_update_slug_rejects_invalid_values(slug):
    with pytest.raises(ValidationError):
        ToolUpdate(slug=slug)


# ── pricing / origin / access ─────────────────────────────────────────────────


@pytest.mark.parametrize("pricing", ["free", "freemium", "paid"])
def test_pricing_accepts_known_values(pricing):
    assert ToolCreate(**_tool_payload(pricing=pricing)).pricing == pricing
    assert ToolUpdate(pricing=pricing).pricing == pricing


@pytest.mark.parametrize("pricing", ["", "FREE", "trial", "opensource"])
def test_pricing_rejects_unknown_values(pricing):
    """开源不是价格档位: pricing 与 is_open_source 是两根正交的轴。"""
    with pytest.raises(ValidationError):
        ToolCreate(**_tool_payload(pricing=pricing))
    with pytest.raises(ValidationError):
        ToolUpdate(pricing=pricing)


@pytest.mark.parametrize("origin", ["cn", "overseas"])
def test_origin_accepts_known_values(origin):
    assert ToolCreate(**_tool_payload(origin=origin)).origin == origin


@pytest.mark.parametrize("origin", ["CN", "global", "", "domestic"])
def test_origin_rejects_unknown_values(origin):
    with pytest.raises(ValidationError):
        ToolCreate(**_tool_payload(origin=origin))


@pytest.mark.parametrize("access", ["direct", "proxy"])
def test_access_accepts_known_values(access):
    assert ToolCreate(**_tool_payload(access=access)).access == access


@pytest.mark.parametrize("access", ["DIRECT", "vpn", ""])
def test_access_rejects_unknown_values(access):
    with pytest.raises(ValidationError):
        ToolCreate(**_tool_payload(access=access))


# ── name ──────────────────────────────────────────────────────────────────────
# 空名/纯空白名以前能 201 落库, 而导出端会把这些行【静默跳过】—— 也就是能建出
# 一个永远不上站的工具/主题, 唯一线索只有 skipped_count。这一组是那条漏洞的钉子。


def test_name_is_stripped():
    assert ToolCreate(**_tool_payload(name="  DeepSeek  ")).name == "DeepSeek"
    assert TopicCreate(slug="t", name="  对话 ").name == "对话"


@pytest.mark.parametrize("name", ["", " ", "   ", "\t", "\n"])
def test_name_rejects_blank(name):
    with pytest.raises(ValidationError):
        ToolCreate(**_tool_payload(name=name))
    with pytest.raises(ValidationError):
        ToolUpdate(name=name)
    with pytest.raises(ValidationError):
        TopicCreate(slug="t", name=name)
    with pytest.raises(ValidationError):
        TopicUpdate(name=name)


def test_name_absent_on_update_is_still_allowed():
    """没传 name 是"不改", 不是"改成空"—— None 不能被当成空值拦掉。"""
    assert ToolUpdate(tagline="简介。").name is None
    assert TopicUpdate(icon="📦").name is None


# ── tagline ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("tagline", ["结束。", "结束.", "结束!", "结束?", "结束…"])
def test_tagline_accepts_terminal_punctuation(tagline):
    assert ToolCreate(**_tool_payload(tagline=tagline)).tagline == tagline
    assert ToolUpdate(tagline=tagline).tagline == tagline


@pytest.mark.parametrize("tagline", ["没有标点", "", "   "])
def test_tagline_rejects_missing_terminal_punctuation(tagline):
    """句末没有标点必须被写入端拦成 422(目标态 schema 已无库级 CHECK, 全靠这一层)。"""
    with pytest.raises(ValidationError):
        ToolCreate(**_tool_payload(tagline=tagline))
    with pytest.raises(ValidationError):
        ToolUpdate(tagline=tagline)


def test_tagline_accepts_max_length():
    """边界内(正好 100 字符)必须放行。中文习惯 21~47 字, 同样信息量的英文约为 2 倍字符。"""
    tagline = "长" * 99 + "。"
    assert len(tagline) == 100
    assert ToolCreate(**_tool_payload(tagline=tagline)).tagline == tagline
    assert ToolUpdate(tagline=tagline).tagline == tagline


def test_tagline_rejects_too_long():
    """101 字符必须拒。这里刻意写死 100/101 而不是引用常量: 常量被误改时这条要能报警。"""
    tagline = "长" * 100 + "。"
    assert len(tagline) == 101
    with pytest.raises(ValidationError):
        ToolCreate(**_tool_payload(tagline=tagline))
    with pytest.raises(ValidationError):
        ToolUpdate(tagline=tagline)


# ── languages ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("languages", [["zh"], ["zh", "en"], ["en", "zh", "ja"]])
def test_languages_accepts_iso_639_1_codes(languages):
    assert ToolCreate(**_tool_payload(languages=languages)).languages == languages


@pytest.mark.parametrize(
    "languages",
    [
        [],
        ["ZH"],
        ["zh", "zh"],
        ["zho"],
        [""],
        ["zh-CN"],
        # 含数字的"两字母"码: islower()+isascii()+len==2 全满足, 必须靠 isalpha 拦下
        ["z1"],
        ["1z"],
        ["zh", "en", "fr", "de", "es", "ja", "ko", "ru", "it"],
    ],
)
def test_languages_rejects_invalid_shapes(languages):
    with pytest.raises(ValidationError):
        ToolCreate(**_tool_payload(languages=languages))
    with pytest.raises(ValidationError):
        ToolUpdate(languages=languages)


# ── tags ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("tags", [[], ["cli"], ["a", "b", "c", "d", "e", "f", "g", "h"]])
def test_tags_accepts_up_to_eight(tags):
    assert ToolCreate(**_tool_payload(tags=tags)).tags == tags


@pytest.mark.parametrize("tags", [["a", "a"], [""], [" padded"], ["padded "], ["x" * 33], list("abcdefghi")])
def test_tags_rejects_invalid_values(tags):
    with pytest.raises(ValidationError):
        ToolCreate(**_tool_payload(tags=tags))
    with pytest.raises(ValidationError):
        ToolUpdate(tags=tags)


# ── 主题归属 ──────────────────────────────────────────────────────────────────


def test_tool_create_primary_topic_must_be_in_topic_ids():
    with pytest.raises(ValidationError):
        ToolCreate(**_tool_payload(topic_ids=[1, 2], primary_topic_id=3))


def test_tool_create_primary_topic_defaults_to_none():
    assert ToolCreate(**_tool_payload(topic_ids=[1])).primary_topic_id is None


def test_tool_topics_update_primary_topic_must_be_in_topic_ids():
    with pytest.raises(ValidationError):
        ToolTopicsUpdate(topic_ids=[1], primary_topic_id=2)


def test_tool_topics_update_omitted_primary_is_none():
    """省略 primary_topic_id 是合法输入: 端点据此保留原主主题。"""
    assert ToolTopicsUpdate(topic_ids=[1]).primary_topic_id is None
    assert ToolTopicsUpdate(topic_ids=[]).topic_ids == []


# ── 链接 url / label ──────────────────────────────────────────────────────────


def test_link_url_accepts_https():
    assert ToolLinkCreate(url="https://example.com").url == "https://example.com"


def test_link_url_accepts_http_for_localhost_only():
    assert ToolLinkCreate(url="http://localhost:3000/app").url == "http://localhost:3000/app"
    assert ToolLinkCreate(url="http://127.0.0.1:8000").url == "http://127.0.0.1:8000"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com",
        "example.com",
        "https://",
        "http://example.com",
        "http://www.example.com/foo",
    ],
)
def test_link_url_rejects_non_https_remote(url):
    """非本地地址一律 https; 缺主机名或非 http(s) 也拒。"""
    with pytest.raises(ValidationError):
        ToolLinkCreate(url=url)


@pytest.mark.parametrize("label", ["website", "api", "docs", "github", "playground", "pricing", "plugin", "other"])
def test_link_label_accepts_known_values(label):
    assert ToolLinkCreate(url="https://example.com", label=label).label == label


@pytest.mark.parametrize("label", ["homepage", "主页", ""])
def test_link_label_rejects_unknown_values(label):
    with pytest.raises(ValidationError):
        ToolLinkCreate(url="https://example.com", label=label)


def test_link_update_url_null_is_allowed():
    """link 更新时 url 省略/传 null 表示不改。"""
    assert ToolLinkUpdate(url=None).url is None
    assert ToolLinkUpdate(url="https://example.com").url == "https://example.com"


def test_link_update_url_still_validates():
    with pytest.raises(ValidationError):
        ToolLinkUpdate(url="http://example.com")


def test_link_defaults():
    link = ToolLinkCreate(url="https://example.com")
    assert link.label == "other"
    assert link.is_primary is False
    assert link.status == "active"
    assert link.sort_order == 0


def test_link_sort_order_rejects_negative():
    with pytest.raises(ValidationError):
        ToolLinkCreate(url="https://example.com", sort_order=-1)


def test_topic_sort_order_rejects_negative():
    with pytest.raises(ValidationError):
        TopicCreate(slug="topic", name="主题", sort_order=-1)


def test_tool_authority_override_rejects_out_of_range():
    """权威度与 ai_authority 同一把尺子(0~9),越界必须 422。"""
    with pytest.raises(ValidationError):
        ToolUpdate(authority_override=-1)
    with pytest.raises(ValidationError):
        ToolUpdate(authority_override=10)


def test_tool_review_score_rejects_out_of_range():
    """review_score 与 ai_score 同一把尺子(0~1000),越界必须 422。"""
    with pytest.raises(ValidationError):
        ToolUpdate(review_score=-1)
    with pytest.raises(ValidationError):
        ToolUpdate(review_score=1001)
