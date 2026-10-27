"""JSON 导出 鉴权 + 数据格式 + 成员规则 完整测试。

导出产物是【两个文件】: topics-{env}.json / tools-{env}.json(顶层数组)。
prod 下额外同步一份无后缀的 topics.json / tools.json 给前端。
"""

import json
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sqlalchemy import update

from app.core.config import Settings
from app.core.database import AsyncSessionLocal
from app.exporters.json_exporter import _invalid_reason, _write_text_atomic, export_to_json
from app.models import Access, Origin, Pricing, Tool, Topic
from app.schemas.common import ExportResponse
from tests.conftest import create_link, create_tool, create_topic, isolated_settings


def _mock_settings(tmp_path: Path, app_env: str = "dev") -> Settings:
    """真 Settings, 只把导出目录指到 tmp_path(避免覆盖真实的 web/data 产物)。

    以前这里用 MagicMock 复刻了一份 export_paths 的后缀逻辑 —— 于是"prod 额外同步
    无后缀文件名"那条用例验的是 mock 自己: 把 config.export_paths 的命名规则改坏也
    不会红。现在只替换【真实现依赖的那个字段】, 命名规则由被测代码自己算。
    """
    overrides: dict[str, Any] = {"export_output_dir": str(tmp_path)}
    if app_env == "prod":
        # prod 的配置校验要求 debug=False 且 api_key 不是默认值(同 test_db_safety)
        overrides |= {"app_debug": False, "api_key": "prod-key"}
    return isolated_settings(app_env=app_env, **overrides)


def _read(path: Any) -> list[Any]:
    with open(path, encoding="utf-8") as handle:
        parsed: list[Any] = json.load(handle)
        return parsed


def _row(**overrides: Any) -> Tool:
    """造一行给 _invalid_reason 用。

    刻意用【真的 Tool】而不是 SimpleNamespace: 假对象会连字段名写错都发现不了
    (_invalid_reason 换个属性名, 测试照样绿)。真模型赋值时会当场报 TypeError。
    overrides 收 Any 是有意的 —— 这个 helper 存在的意义之一就是塞进"库里才会有"的
    脏值(pricing="enterprise" 这种直连改库产物), 那正是类型系统禁止的取值。
    """
    values: dict[str, Any] = {
        "slug": "x",
        "name": "X",
        "tagline": "句末有标点。",
        "pricing": Pricing.FREE,
        "origin": Origin.CN,
        "access": Access.DIRECT,
        "languages": ["zh"],
        "tags": [],
    }
    values.update(overrides)
    return Tool(**values)


# ── 鉴权 ──────────────────────────────────────────────────────────────────────


async def test_export_without_api_key(anon_client):
    resp = await anon_client.post("/api/v1/export")
    assert resp.status_code == 401


async def test_export_with_wrong_api_key(anon_client):
    resp = await anon_client.post("/api/v1/export", headers={"X-API-Key": "wrong"})
    assert resp.status_code == 401


# ── 基本契约 ──────────────────────────────────────────────────────────────────


async def test_export_success(async_client, tmp_path):
    mock = _mock_settings(tmp_path)
    with patch("app.exporters.json_exporter.get_settings", return_value=mock):
        resp = await async_client.post("/api/v1/export")

    assert resp.status_code == 200
    data = resp.json()
    assert "exported_at" in data
    # output_path 只回文件名, 不回服务端绝对路径(响应会进 CI 日志, 不该暴露部署布局)
    assert data["output_path"] == "topics-dev.json, tools-dev.json"
    assert str(tmp_path) not in data["output_path"]
    assert data["topics_count"] == 0
    assert data["tools_count"] == 0
    assert data["skipped_count"] == 0
    assert data["skipped_reasons"] == {}
    assert data["app_env"] == "dev"
    assert data["synced_frontend"] is False
    assert (tmp_path / "topics-dev.json").exists()
    assert (tmp_path / "tools-dev.json").exists()
    assert _read(tmp_path / "topics-dev.json") == []
    assert _read(tmp_path / "tools-dev.json") == []


async def test_export_to_json_returns_export_response(tmp_path):
    """导出器直接返回 ExportResponse, 避免返回值与响应 schema 隐式对齐。"""
    mock = _mock_settings(tmp_path)
    with patch("app.exporters.json_exporter.get_settings", return_value=mock):
        async with AsyncSessionLocal() as session:
            result = await export_to_json(session)

    assert isinstance(result, ExportResponse)
    assert result.output_path == "topics-dev.json, tools-dev.json"
    assert result.skipped_count == 0
    assert result.skipped_reasons == {}
    assert result.synced_frontend is False
    assert result.app_env == "dev"


async def test_export_syncs_frontend_names_in_prod(async_client, tmp_path):
    """prod 下额外写无后缀的 topics.json / tools.json 给前端。"""
    mock = _mock_settings(tmp_path, app_env="prod")
    with patch("app.exporters.json_exporter.get_settings", return_value=mock):
        resp = await async_client.post("/api/v1/export")

    assert resp.status_code == 200
    assert resp.json()["synced_frontend"] is True
    assert resp.json()["app_env"] == "prod"
    for name in ("topics-prod.json", "tools-prod.json", "topics.json", "tools.json"):
        assert (tmp_path / name).exists(), name


# ── 成员规则 ──────────────────────────────────────────────────────────────────


async def test_export_only_includes_published_with_active_link(async_client, tmp_path):
    """tools[] 成员 = published 且存在 active 链接, 两个条件缺一不可。"""
    await create_tool(
        async_client,
        slug="published",
        name="已发布",
        status="published",
        links=[{"url": "https://published.example.com"}],
    )
    await create_tool(async_client, slug="draft", name="草稿", status="draft")
    await create_tool(async_client, slug="pending", name="待审", status="pending")
    await create_tool(async_client, slug="archived", name="已下架", status="archived")
    # published 但没有链接
    await create_tool(async_client, slug="no-link", name="无链接", status="published")
    # published 但链接都不是 active
    await create_tool(
        async_client,
        slug="broken-only",
        name="只有死链",
        status="published",
        links=[{"url": "https://broken.example.com", "status": "broken"}],
    )

    mock = _mock_settings(tmp_path)
    with patch("app.exporters.json_exporter.get_settings", return_value=mock):
        resp = await async_client.post("/api/v1/export")

    assert resp.json()["tools_count"] == 1
    assert [tool["id"] for tool in _read(tmp_path / "tools-dev.json")] == ["published"]


async def test_export_skips_tool_without_link(async_client, tmp_path):
    """没有链接的工具不导出(前端 url 必填, 空 url 会导致构建失败)。"""
    await create_tool(async_client, slug="no-link", name="无链接", status="published")

    mock = _mock_settings(tmp_path)
    with patch("app.exporters.json_exporter.get_settings", return_value=mock):
        resp = await async_client.post("/api/v1/export")

    assert resp.json()["tools_count"] == 0
    assert _read(tmp_path / "tools-dev.json") == []


async def test_export_skips_tool_with_only_inactive_links(async_client, tmp_path):
    """仅有非 active 链接(失效/禁用)的工具不导出, 避免死链进入前端。"""
    await create_tool(
        async_client,
        slug="dead-link",
        name="死链工具",
        status="published",
        links=[
            {"url": "https://broken.example.com", "status": "broken"},
            {"url": "https://disabled.example.com", "status": "disabled"},
        ],
    )

    mock = _mock_settings(tmp_path)
    with patch("app.exporters.json_exporter.get_settings", return_value=mock):
        resp = await async_client.post("/api/v1/export")

    assert resp.json()["tools_count"] == 0
    assert _read(tmp_path / "tools-dev.json") == []


async def test_export_prefers_primary_active_link(async_client, tmp_path):
    """多个 active 链接时优先选 is_primary 的, 其余进 links[]。"""
    await create_tool(
        async_client,
        slug="multi-link",
        name="多链接",
        status="published",
        links=[
            {"url": "https://secondary.example.com"},
            {"url": "https://primary.example.com", "is_primary": True},
        ],
    )

    mock = _mock_settings(tmp_path)
    with patch("app.exporters.json_exporter.get_settings", return_value=mock):
        await async_client.post("/api/v1/export")

    prod = _read(tmp_path / "tools-dev.json")[0]
    assert prod["url"] == "https://primary.example.com/"
    assert prod["links"] == [{"label": "other", "url": "https://secondary.example.com/"}]


async def test_export_skips_broken_primary_link(async_client, tmp_path):
    """主链接失效 → 回退到第一个正常链接, 且该 URL 不会在 links[] 里出现两次。"""
    tool = await create_tool(
        async_client,
        slug="broken-primary",
        name="失效主链接工具",
        status="published",
        links=[
            {"url": "https://secondary.com"},
            {"url": "https://primary.com", "is_primary": True},
        ],
    )
    primary_link = next(link for link in tool["links"] if link["is_primary"])
    resp = await async_client.put(
        f"/api/v1/tools/{tool['id']}/links/{primary_link['id']}",
        json={"status": "broken"},
    )
    assert resp.status_code == 200

    mock = _mock_settings(tmp_path)
    with patch("app.exporters.json_exporter.get_settings", return_value=mock):
        await async_client.post("/api/v1/export")

    prod = _read(tmp_path / "tools-dev.json")[0]
    assert prod["url"] == "https://secondary.com/"
    assert "links" not in prod


# ── 数据格式 ──────────────────────────────────────────────────────────────────


async def test_export_data_format(async_client, tmp_path):
    """验证导出 JSON 的键名/类型与 schema/*.data.jsonc 一致。"""
    topic = await create_topic(
        async_client,
        slug="chat",
        name="对话",
        icon="MessageSquare",
        description="通用对话主题。",
        sort_order=100,
    )
    tool = await create_tool(
        async_client,
        slug="chatgpt",
        name="ChatGPT",
        description="AI 对话助手",
        tagline="通用对话助手与知识问答工具。",
        pricing="freemium",
        is_open_source=True,
        origin="overseas",
        access="proxy",
        languages=["zh", "en"],
        tags=["chat", "llm"],
        is_featured=True,
        status="published",
        topic_ids=[topic["id"]],
        primary_topic_id=topic["id"],
        links=[{"url": "https://www.chat.openai.com:443/#top", "label": "website", "is_primary": True}],
    )
    await create_link(async_client, tool["id"], url="https://docs.example.com/guide/", label="docs")

    mock = _mock_settings(tmp_path)
    with patch("app.exporters.json_exporter.get_settings", return_value=mock):
        await async_client.post("/api/v1/export")

    topics = _read(tmp_path / "topics-dev.json")
    assert topics == [
        {
            "id": "chat",
            "name": "对话",
            "icon": "MessageSquare",
            "description": "通用对话主题。",
            "toolCount": 1,
        }
    ]

    prod = _read(tmp_path / "tools-dev.json")[0]
    assert prod["id"] == "chatgpt"
    assert prod["name"] == "ChatGPT"
    assert prod["tagline"] == "通用对话助手与知识问答工具。"
    assert prod["description"] == "AI 对话助手"
    # url 是写入端归一化的结果: 去 www、去默认端口、去 fragment、去尾斜杠(根路径保留)
    assert prod["url"] == "https://chat.openai.com/"
    assert prod["topics"] == ["chat"]
    assert prod["tags"] == ["chat", "llm"]
    assert prod["pricing"] == "freemium"
    assert prod["openSource"] is True
    assert prod["origin"] == "overseas"
    assert prod["access"] == "proxy"
    assert prod["languages"] == ["zh", "en"]
    assert prod["featured"] is True
    assert prod["publishedAt"] == tool["published_at"]
    # lastUpdatedAt 来自审计列 updated_at(改库时间), 不是工具在上游的更新日期
    assert prod["lastUpdatedAt"] == tool["updated_at"][:10]
    assert prod["links"] == [{"label": "docs", "url": "https://docs.example.com/guide"}]


async def test_export_omits_null_optional_keys(async_client, tmp_path):
    """description 为 NULL 时【省略键】, 不输出 null。"""
    topic = await create_topic(async_client, slug="bare", name="无描述")
    await create_tool(
        async_client,
        slug="bare-tool",
        name="无描述工具",
        status="published",
        topic_ids=[topic["id"]],
        primary_topic_id=topic["id"],
        links=[{"url": "https://bare.example.com"}],
    )

    mock = _mock_settings(tmp_path)
    with patch("app.exporters.json_exporter.get_settings", return_value=mock):
        await async_client.post("/api/v1/export")

    topic_item = _read(tmp_path / "topics-dev.json")[0]
    assert "description" not in topic_item

    prod = _read(tmp_path / "tools-dev.json")[0]
    assert "description" not in prod
    # 反面: lastUpdatedAt 取自 NOT NULL 的审计列 updated_at, 永远存在, 不参与"省略键"
    assert prod["lastUpdatedAt"]


# ── 主题归属 + 计数口径 ───────────────────────────────────────────────────────


async def test_export_excludes_disabled_topic(async_client, tmp_path):
    """禁用的主题不进 topics[], 工具挂在它上面也不出现在 tools[].topics[]。"""
    active = await create_topic(async_client, slug="active-topic", name="启用")
    disabled = await create_topic(async_client, slug="disabled-topic", name="禁用", status="disabled")
    await create_tool(
        async_client,
        slug="mixed-topic",
        name="混合主题",
        status="published",
        topic_ids=[active["id"], disabled["id"]],
        primary_topic_id=active["id"],
        links=[{"url": "https://mixed.example.com"}],
    )

    mock = _mock_settings(tmp_path)
    with patch("app.exporters.json_exporter.get_settings", return_value=mock):
        await async_client.post("/api/v1/export")

    assert [topic["id"] for topic in _read(tmp_path / "topics-dev.json")] == ["active-topic"]
    assert _read(tmp_path / "tools-dev.json")[0]["topics"] == ["active-topic"]


async def test_export_orphan_tool_falls_back_to_uncategorized(async_client, tmp_path):
    """工具所有主题都被禁用时回退到合成的 misc, 且 topics[] 里要补上这一项。"""
    disabled = await create_topic(async_client, slug="disabled-only", name="禁用", status="disabled")
    await create_tool(
        async_client,
        slug="orphan",
        name="孤儿工具",
        status="published",
        topic_ids=[disabled["id"]],
        primary_topic_id=disabled["id"],
        links=[{"url": "https://orphan.example.com"}],
    )

    mock = _mock_settings(tmp_path)
    with patch("app.exporters.json_exporter.get_settings", return_value=mock):
        await async_client.post("/api/v1/export")

    assert _read(tmp_path / "tools-dev.json")[0]["topics"] == ["misc"]
    assert _read(tmp_path / "topics-dev.json")[-1] == {"id": "misc", "name": "未分类", "icon": "📦", "toolCount": 1}


async def test_export_omits_uncategorized_when_not_needed(async_client, tmp_path):
    """没有孤儿工具时不应凭空追加未分类主题。"""
    topic = await create_topic(async_client, slug="only-topic", name="正常")
    await create_tool(
        async_client,
        slug="normal",
        name="正常工具",
        status="published",
        topic_ids=[topic["id"]],
        primary_topic_id=topic["id"],
        links=[{"url": "https://normal.example.com"}],
    )

    mock = _mock_settings(tmp_path)
    with patch("app.exporters.json_exporter.get_settings", return_value=mock):
        await async_client.post("/api/v1/export")

    assert [topic["id"] for topic in _read(tmp_path / "topics-dev.json")] == ["only-topic"]


async def test_export_reuses_real_misc_topic(async_client, tmp_path):
    """已存在启用的 misc 主题时应复用, 不得产生重复 id。"""
    real = await create_topic(async_client, slug="misc", name="其他", icon="📦")
    disabled = await create_topic(async_client, slug="disabled-x", name="禁用", status="disabled")
    await create_tool(
        async_client,
        slug="mixed",
        name="混合",
        status="published",
        topic_ids=[real["id"], disabled["id"]],
        primary_topic_id=real["id"],
        links=[{"url": "https://mixed2.example.com"}],
    )

    mock = _mock_settings(tmp_path)
    with patch("app.exporters.json_exporter.get_settings", return_value=mock):
        await async_client.post("/api/v1/export")

    assert _read(tmp_path / "tools-dev.json")[0]["topics"] == ["misc"]
    miscs = [topic for topic in _read(tmp_path / "topics-dev.json") if topic["id"] == "misc"]
    assert len(miscs) == 1
    assert miscs[0]["name"] == "其他"
    assert miscs[0]["toolCount"] == 1


async def test_export_tool_count_matches_member_rule(async_client, tmp_path):
    """toolCount 口径必须与 tools[] 成员规则一致(否则会出现导航徽标 12 / 主题页 11)。"""
    topic = await create_topic(async_client, slug="count-topic", name="计数")
    await create_tool(
        async_client,
        slug="counted",
        name="计入",
        status="published",
        topic_ids=[topic["id"]],
        primary_topic_id=topic["id"],
        links=[{"url": "https://counted.example.com"}],
    )
    # published 但无链接: 不进 tools[], 也不计入 toolCount
    await create_tool(
        async_client,
        slug="no-link",
        name="无链接",
        status="published",
        topic_ids=[topic["id"]],
        primary_topic_id=topic["id"],
    )
    # pending 有链接: 同样不进 tools[]
    await create_tool(
        async_client,
        slug="pending",
        name="待审",
        status="pending",
        topic_ids=[topic["id"]],
        primary_topic_id=topic["id"],
        links=[{"url": "https://pending.example.com"}],
    )

    mock = _mock_settings(tmp_path)
    with patch("app.exporters.json_exporter.get_settings", return_value=mock):
        await async_client.post("/api/v1/export")

    tools = _read(tmp_path / "tools-dev.json")
    topics = _read(tmp_path / "topics-dev.json")
    assert [tool["id"] for tool in tools] == ["counted"]
    assert topics[0]["toolCount"] == 1


# ── 排序 ──────────────────────────────────────────────────────────────────────


async def test_export_stable_order_tiebreak_by_id(async_client, tmp_path):
    """ai_score 与 published_at 均相同时按 id 升序, 保证导出顺序稳定。"""
    first = await create_tool(
        async_client, slug="pa", name="PA", status="published", links=[{"url": "https://a.example.com"}]
    )
    second = await create_tool(
        async_client, slug="pb", name="PB", status="published", links=[{"url": "https://b.example.com"}]
    )
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Tool)
            .where(Tool.id.in_([first["id"], second["id"]]))
            .values(ai_score=5, published_at=date(2026, 1, 1))
        )
        await session.commit()

    mock = _mock_settings(tmp_path)
    with patch("app.exporters.json_exporter.get_settings", return_value=mock):
        await async_client.post("/api/v1/export")

    assert [tool["id"] for tool in _read(tmp_path / "tools-dev.json")] == ["pa", "pb"]


async def test_export_tool_order_by_ai_score_desc(async_client, tmp_path):
    low = await create_tool(
        async_client, slug="low", name="低", status="published", links=[{"url": "https://low.example.com"}]
    )
    high = await create_tool(
        async_client,
        slug="high",
        name="高",
        status="published",
        ai_score=100,
        links=[{"url": "https://high.example.com"}],
    )

    mock = _mock_settings(tmp_path)
    with patch("app.exporters.json_exporter.get_settings", return_value=mock):
        await async_client.post("/api/v1/export")

    assert [tool["id"] for tool in _read(tmp_path / "tools-dev.json")] == ["high", "low"]
    assert high["ai_score"] == 100
    assert low["ai_score"] == 0


async def test_export_link_and_topic_order_is_deterministic(async_client, tmp_path):
    """无 primary 时按 sort_order/id 取首个 active 链接; 主题按 is_primary DESC, topic_id ASC。"""
    topic_b = await create_topic(async_client, slug="topic-b", name="B")
    topic_a = await create_topic(async_client, slug="topic-a", name="A")
    await create_tool(
        async_client,
        slug="multi",
        name="多链接",
        status="published",
        topic_ids=[topic_b["id"], topic_a["id"]],
        primary_topic_id=topic_b["id"],
        links=[{"url": "https://first.example.com"}, {"url": "https://second.example.com"}],
    )

    mock = _mock_settings(tmp_path)
    with patch("app.exporters.json_exporter.get_settings", return_value=mock):
        await async_client.post("/api/v1/export")

    prod = _read(tmp_path / "tools-dev.json")[0]
    assert prod["url"] == "https://first.example.com/"
    assert prod["topics"] == ["topic-b", "topic-a"]


# ── 脏数据兜底 ────────────────────────────────────────────────────────────────


async def test_export_skips_blank_name_record(async_client, tmp_path):
    """直连改库绕过写入端校验的行(名字为空)应被跳过, 避免前端构建失败。"""
    await create_tool(
        async_client, slug="good", name="Good", status="published", links=[{"url": "https://good.example.com"}]
    )
    bad = await create_tool(
        async_client, slug="bad-name", name="Bad", status="published", links=[{"url": "https://bad.example.com"}]
    )
    async with AsyncSessionLocal() as session:
        await session.execute(update(Tool).where(Tool.id == bad["id"]).values(name=""))
        await session.commit()

    mock = _mock_settings(tmp_path)
    with patch("app.exporters.json_exporter.get_settings", return_value=mock):
        await async_client.post("/api/v1/export")

    assert [tool["id"] for tool in _read(tmp_path / "tools-dev.json")] == ["good"]


async def test_export_reports_skipped_rows_by_reason(async_client, tmp_path):
    """被跳过的行不能只留在服务端日志里: 响应要给出总数与按原因的计数。"""
    ghost_topic = await create_topic(async_client, slug="ghost-topic", name="会被清空")
    # 工具 A: published 但没有可用链接
    await create_tool(async_client, slug="no-link", name="无链接", status="published")
    # 工具 B: published 有链接, 但名字为空
    bad = await create_tool(
        async_client, slug="bad-name", name="坏名字", status="published", links=[{"url": "https://bad.example.com"}]
    )
    async with AsyncSessionLocal() as session:
        await session.execute(update(Topic).where(Topic.id == ghost_topic["id"]).values(name=""))
        await session.execute(update(Tool).where(Tool.id == bad["id"]).values(name=""))
        await session.commit()

    mock = _mock_settings(tmp_path)
    with patch("app.exporters.json_exporter.get_settings", return_value=mock):
        resp = await async_client.post("/api/v1/export")

    data = resp.json()
    assert data["skipped_count"] == 3
    assert data["skipped_reasons"] == {
        "主题 slug/name 为空": 1,
        "工具无可用链接": 1,
        "工具 slug/name 为空": 1,
    }
    # 被跳过的都没进产物
    assert data["topics_count"] == 0
    assert data["tools_count"] == 0


def test_invalid_reason_accepts_valid_row():
    assert _invalid_reason(_row(), "https://example.com") is None


def test_invalid_reason_flags_blank_name():
    assert _invalid_reason(_row(name=""), "https://example.com") == "slug/name 为空"


def test_invalid_reason_flags_blank_tagline():
    assert _invalid_reason(_row(tagline=""), "https://example.com") == "tagline 为空"


def test_invalid_reason_flags_blank_url():
    assert _invalid_reason(_row(), "") == "url 为空"


def test_invalid_reason_flags_unknown_pricing():
    """ENUM 列让这种行不可能从 API 进来, 但直连改库仍可能; 导出端要兜住。"""
    reason = _invalid_reason(_row(pricing="enterprise"), "https://example.com")
    # 先收口再判子串: _invalid_reason 返回 None 时 "pricing" in None 抛的是 TypeError,
    # 报错信息会指向这里而不是"它没返回原因"
    assert reason is not None
    assert "pricing" in reason


def test_invalid_reason_flags_empty_languages():
    assert _invalid_reason(_row(languages=[]), "https://example.com") == "languages 为空"


# ── 原子写入 ──────────────────────────────────────────────────────────────────


async def test_write_text_atomic_replaces_and_leaves_no_tmp(tmp_path):
    """原子写入应覆盖旧内容且不残留临时文件。"""
    target = tmp_path / "topics-dev.json"
    _write_text_atomic(target, "old")
    _write_text_atomic(target, "new")
    assert target.read_text(encoding="utf-8") == "new"
    assert list(tmp_path.glob(".*tmp")) == []


async def test_write_text_atomic_creates_parent_dir(tmp_path):
    target = tmp_path / "nested" / "dir" / "tools-dev.json"
    _write_text_atomic(target, "[]")
    assert target.read_text(encoding="utf-8") == "[]"
