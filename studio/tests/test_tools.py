"""工具 CRUD + 发布逻辑 + 状态机 + 过滤 + 分页 完整测试。"""

from tests.conftest import create_link, create_tool, create_topic

# 建工具的最小合法负载(必填字段一个都不能少: 危险的默认值刻意不给)
_MINIMAL = {
    "slug": "mini",
    "name": "最小工具",
    "tagline": "一个最小的工具。",
    "pricing": "free",
    "origin": "cn",
    "access": "direct",
    "languages": ["zh"],
}


async def test_create_tool_minimal(async_client):
    """必填字段之外全部走默认值。"""
    resp = await async_client.post("/api/v1/tools", json=_MINIMAL)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["name"] == "最小工具"
    assert data["pricing"] == "free"
    assert data["origin"] == "cn"
    assert data["access"] == "direct"
    assert data["languages"] == ["zh"]
    assert data["is_open_source"] is False
    assert data["is_featured"] is False
    assert data["status"] == "draft"
    assert data["description"] is None
    assert data["tags"] == []
    assert data["topic_ids"] == []
    assert data["primary_topic_id"] is None
    assert data["topics"] == []
    assert data["links"] == []
    assert data["published_at"] is None


async def test_create_tool_requires_pricing_origin_access_languages(async_client):
    """pricing / origin / access / languages 刻意没有默认值, 缺失必须 422。"""
    for missing in ("pricing", "origin", "access", "languages"):
        payload = {key: value for key, value in _MINIMAL.items() if key != missing}
        resp = await async_client.post("/api/v1/tools", json=payload)
        assert resp.status_code == 422, f"missing {missing}: {resp.text}"


async def test_create_tool_with_links_and_topics(async_client):
    topic = await create_topic(async_client, slug="topic", name="主题")
    data = await create_tool(
        async_client,
        slug="full",
        name="完整工具",
        description="描述",
        pricing="paid",
        is_open_source=True,
        is_featured=True,
        tags=["cli", "开源"],
        topic_ids=[topic["id"]],
        primary_topic_id=topic["id"],
        links=[{"url": "https://example.com", "label": "website", "is_primary": True}],
    )
    assert len(data["links"]) == 1
    assert data["links"][0]["url"] == "https://example.com/"  # 归一化后根路径带尾斜杠
    assert data["links"][0]["label"] == "website"
    assert data["links"][0]["is_primary"] is True
    assert data["topic_ids"] == [topic["id"]]
    assert data["primary_topic_id"] == topic["id"]
    assert [t["id"] for t in data["topics"]] == [topic["id"]]
    assert data["tags"] == ["cli", "开源"]
    assert data["is_open_source"] is True


async def test_create_tool_rejects_multiple_primary_links(async_client):
    """同一次 payload 里两个主链接应 400, 而不是靠随机胜出在库里留下两个主链接。"""
    resp = await async_client.post(
        "/api/v1/tools",
        json={
            **_MINIMAL,
            "slug": "multi-primary",
            "name": "多主链接",
            "links": [
                {"url": "https://a.example.com", "is_primary": True},
                {"url": "https://b.example.com", "is_primary": True},
            ],
        },
    )
    assert resp.status_code == 400, resp.text
    assert "primary" in resp.json()["detail"].lower()


async def test_create_tool_duplicate_slug(async_client):
    await create_tool(async_client, slug="dup", name="A")
    resp = await async_client.post("/api/v1/tools", json={**_MINIMAL, "slug": "dup", "name": "B"})
    assert resp.status_code == 409


async def test_create_tool_duplicate_name(async_client):
    await create_tool(async_client, slug="tool-a", name="重复名")
    resp = await async_client.post("/api/v1/tools", json={**_MINIMAL, "slug": "tool-b", "name": "重复名"})
    assert resp.status_code == 409


async def test_create_tool_rejects_duplicate_link_urls(async_client):
    """links 内归一化后重复的 URL 应 400, 而非撞唯一约束的 409。"""
    resp = await async_client.post(
        "/api/v1/tools",
        json={
            **_MINIMAL,
            "slug": "dup-link",
            "name": "重复链接",
            "links": [{"url": "https://a.example.com"}, {"url": "https://www.a.example.com/"}],
        },
    )
    assert resp.status_code == 400, resp.text
    assert "Duplicate" in resp.json()["detail"]

    resp = await async_client.get("/api/v1/tools")
    assert resp.json() == []


async def test_publish_sets_published_at(async_client):
    """草稿工具发布时 published_at 从 null 变为日期。流程: draft -> pending -> published。"""
    tool = await create_tool(async_client, slug="draft", name="草稿", status="draft")
    assert tool["published_at"] is None

    # 提交审核: draft -> pending
    resp = await async_client.put(f"/api/v1/tools/{tool['id']}", json={"status": "pending"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["published_at"] is None

    # 审核通过发布: pending -> published
    resp = await async_client.put(f"/api/v1/tools/{tool['id']}", json={"status": "published"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "published"
    assert data["published_at"] is not None


async def test_published_at_does_not_change_on_reupdate(async_client):
    """已发布工具再次更新, published_at 不变。"""
    tool = await create_tool(async_client, slug="pub", name="已发布", status="published")
    original = tool["published_at"]
    assert original is not None

    resp = await async_client.put(f"/api/v1/tools/{tool['id']}", json={"description": "改描述"})
    assert resp.status_code == 200
    assert resp.json()["published_at"] == original


async def test_published_at_written_only_once(async_client):
    """转 published -> archived -> published, published_at 只在【首次】写入。"""
    tool = await create_tool(async_client, slug="once", name="只写一次", status="published")
    first = tool["published_at"]
    assert first is not None

    resp = await async_client.put(f"/api/v1/tools/{tool['id']}", json={"status": "archived"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["published_at"] == first

    resp = await async_client.put(f"/api/v1/tools/{tool['id']}", json={"status": "published"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["published_at"] == first


async def test_draft_to_published_rejected(async_client):
    """draft -> published 必须被拒: 先经过 pending, 否则待审核只是装饰。"""
    tool = await create_tool(async_client, slug="jump", name="跳级", status="draft")
    resp = await async_client.put(f"/api/v1/tools/{tool['id']}", json={"status": "published"})
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert "Invalid status transition" in detail
    assert "draft" in detail
    assert "published" in detail


async def test_invalid_transition_returns_409(async_client):
    """请求本身没问题, 是资源当前状态不允许 -> 409(不再是旧版的 400)。"""
    tool = await create_tool(async_client, slug="bad-move", name="非法迁移", status="published")
    resp = await async_client.put(f"/api/v1/tools/{tool['id']}", json={"status": "draft"})
    assert resp.status_code == 409, resp.text
    assert "Invalid status transition" in resp.json()["detail"]


async def test_archived_can_return_to_published(async_client):
    tool = await create_tool(async_client, slug="revive", name="复活", status="archived")
    assert tool["status"] == "archived"
    resp = await async_client.put(f"/api/v1/tools/{tool['id']}", json={"status": "published"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "published"


async def test_create_rejects_published_status(async_client):
    """创建时不允许直接 published, 必须走 draft -> pending -> published。"""
    resp = await async_client.post("/api/v1/tools", json={**_MINIMAL, "slug": "direct", "status": "published"})
    assert resp.status_code == 400
    assert "draft" in resp.json()["detail"]
    assert "pending" in resp.json()["detail"]


async def test_create_rejects_archived_status(async_client):
    resp = await async_client.post("/api/v1/tools", json={**_MINIMAL, "slug": "direct", "status": "archived"})
    assert resp.status_code == 400


async def test_create_allows_pending_status(async_client):
    resp = await async_client.post("/api/v1/tools", json={**_MINIMAL, "slug": "pending", "status": "pending"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "pending"


async def test_filter_by_status(async_client):
    await create_tool(async_client, slug="t-pub", name="已发布", status="published")
    await create_tool(async_client, slug="t-draft", name="草稿", status="draft")
    await create_tool(async_client, slug="t-arch", name="已下架", status="archived")

    resp = await async_client.get("/api/v1/tools?status=published")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "已发布"


async def test_filter_by_featured(async_client):
    await create_tool(async_client, slug="t-yes", name="精选", is_featured=True)
    await create_tool(async_client, slug="t-no", name="普通", is_featured=False)

    resp = await async_client.get("/api/v1/tools?featured=true")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["is_featured"] is True


async def test_filter_by_topic(async_client):
    topic = await create_topic(async_client, slug="topic", name="主题")
    await create_tool(async_client, slug="t-in", name="在主题里", topic_ids=[topic["id"]])
    await create_tool(async_client, slug="t-out", name="不在主题里")

    resp = await async_client.get(f"/api/v1/tools?topic_id={topic['id']}")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "在主题里"


async def test_list_tools_total_count_header(async_client):
    """列表带 X-Total-Count, 且分页不改变总数。"""
    for i in range(5):
        await create_tool(async_client, slug=f"total-{i}", name=f"T{i}")

    resp = await async_client.get("/api/v1/tools?page=1&page_size=2")
    assert resp.headers["X-Total-Count"] == "5"
    assert len(resp.json()) == 2


async def test_pagination(async_client):
    for i in range(5):
        await create_tool(async_client, slug=f"page-{i}", name=f"P{i}")

    assert len((await async_client.get("/api/v1/tools?page=1&page_size=2")).json()) == 2
    assert len((await async_client.get("/api/v1/tools?page=2&page_size=2")).json()) == 2
    assert len((await async_client.get("/api/v1/tools?page=3&page_size=2")).json()) == 1


async def test_list_tools_order_is_deterministic_on_tie(async_client):
    """ai_score / published_at 并列时按 id 升序, 保证翻页顺序稳定。"""
    a = await create_tool(async_client, slug="tie-a", name="并列A")
    b = await create_tool(async_client, slug="tie-b", name="并列B")
    c = await create_tool(async_client, slug="tie-c", name="并列C")
    expected = [a["id"], b["id"], c["id"]]

    page1 = (await async_client.get("/api/v1/tools?page=1&page_size=2")).json()
    page2 = (await async_client.get("/api/v1/tools?page=2&page_size=2")).json()
    assert [t["id"] for t in page1 + page2] == expected


async def test_list_tools_rejects_out_of_range_status(async_client):
    """status 是 StrEnum, 非法值应 422 而非静默返回空列表。"""
    resp = await async_client.get("/api/v1/tools?status=99")
    assert resp.status_code == 422


async def test_get_tool_by_id(async_client):
    tool = await create_tool(async_client, slug="get-me", name="按id取")
    resp = await async_client.get(f"/api/v1/tools/{tool['id']}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "按id取"


async def test_get_tool_not_found(async_client):
    resp = await async_client.get("/api/v1/tools/99999")
    assert resp.status_code == 404


async def test_update_tool(async_client):
    tool = await create_tool(async_client, slug="upd", name="旧名")
    resp = await async_client.put(
        f"/api/v1/tools/{tool['id']}",
        json={"name": "新名", "pricing": "paid", "origin": "overseas", "access": "proxy"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "新名"
    assert data["pricing"] == "paid"
    assert data["origin"] == "overseas"
    assert data["access"] == "proxy"


async def test_update_tool_not_found(async_client):
    resp = await async_client.put("/api/v1/tools/99999", json={"name": "无此工具"})
    assert resp.status_code == 404


async def test_update_tool_slug_conflict(async_client):
    await create_tool(async_client, slug="slug-a", name="A")
    tool_b = await create_tool(async_client, slug="slug-b", name="B")
    resp = await async_client.put(f"/api/v1/tools/{tool_b['id']}", json={"slug": "slug-a"})
    assert resp.status_code == 409


async def test_delete_tool(async_client):
    tool = await create_tool(async_client, slug="del", name="待删")
    resp = await async_client.delete(f"/api/v1/tools/{tool['id']}")
    assert resp.status_code == 204
    resp = await async_client.get(f"/api/v1/tools/{tool['id']}")
    assert resp.status_code == 404


async def test_delete_tool_not_found(async_client):
    resp = await async_client.delete("/api/v1/tools/99999")
    assert resp.status_code == 404


async def test_create_tool_rejects_tagline_without_terminal_punctuation(async_client):
    """tagline 句末必须是标点: 写入端在 422 拦下(目标态 schema 已无库级 CHECK)。"""
    resp = await async_client.post(
        "/api/v1/tools",
        json={**_MINIMAL, "slug": "no-punct", "tagline": "没有标点结尾的简介"},
    )
    assert resp.status_code == 422, resp.text
    # 422 用 FastAPI 默认形态(detail 是错误对象数组, 与 OpenAPI 的 HTTPValidationError 一致)
    assert any("标点" in err["msg"] for err in resp.json()["detail"])


async def test_tagline_accepts_allowed_terminal_punctuation(async_client):
    """中文句号 / 句点 / 感叹号 / 问号 / 省略号都算合法结尾。"""
    for index, suffix in enumerate(("。", ".", "!", "?", "…")):
        resp = await async_client.post(
            "/api/v1/tools",
            json={
                **_MINIMAL,
                "slug": f"punct-{index}",
                "name": f"标点工具{index}",
                "tagline": f"测试结尾{suffix}",
            },
        )
        assert resp.status_code == 201, f"{suffix!r}: {resp.text}"


async def test_update_tool_rejects_tagline_without_punctuation(async_client):
    tool = await create_tool(async_client, slug="punct-upd", name="标点更新")
    resp = await async_client.put(f"/api/v1/tools/{tool['id']}", json={"tagline": "没有标点"})
    assert resp.status_code == 422


async def test_create_tool_rejects_invalid_languages(async_client):
    """languages 必须 1~8 项、两字母小写、不重复。"""
    bad_values = [
        [],
        ["ZH"],
        ["zh", "zh"],
        ["zho"],
        [""],
        ["zh", "en", "fr", "de", "es", "ja", "ko", "ru", "it"],
    ]
    for index, bad in enumerate(bad_values):
        resp = await async_client.post(
            "/api/v1/tools",
            json={**_MINIMAL, "slug": f"bad-lang-{index}", "languages": bad},
        )
        assert resp.status_code == 422, f"{bad!r}: {resp.text}"


async def test_update_tool_rejects_invalid_languages(async_client):
    tool = await create_tool(async_client, slug="lang-upd", name="语言更新")
    for bad in ([], ["ZH"], ["zh", "zh"]):
        resp = await async_client.put(f"/api/v1/tools/{tool['id']}", json={"languages": bad})
        assert resp.status_code == 422, f"{bad!r}: {resp.text}"


async def test_create_tool_rejects_too_many_tags(async_client):
    resp = await async_client.post(
        "/api/v1/tools",
        json={**_MINIMAL, "slug": "many-tags", "tags": [f"tag{i}" for i in range(9)]},
    )
    assert resp.status_code == 422


async def test_create_tool_rejects_duplicate_tags(async_client):
    resp = await async_client.post("/api/v1/tools", json={**_MINIMAL, "slug": "dup-tags", "tags": ["a", "a"]})
    assert resp.status_code == 422


async def test_update_tool_replaces_tags(async_client):
    """tags 是 JSON 列: 更新是全量替换, 不是追加。"""
    tool = await create_tool(async_client, slug="tags", name="标签", tags=["a", "b"])
    assert tool["tags"] == ["a", "b"]

    resp = await async_client.put(f"/api/v1/tools/{tool['id']}", json={"tags": ["c"]})
    assert resp.status_code == 200
    assert resp.json()["tags"] == ["c"]

    resp = await async_client.put(f"/api/v1/tools/{tool['id']}", json={"tags": []})
    assert resp.status_code == 200
    assert resp.json()["tags"] == []


async def test_update_tool_ignores_explicit_null(async_client):
    """显式传 null 的非空字段应视为未提供, 不应触发 500。"""
    topic = await create_topic(async_client, slug="null-topic", name="空值主题")
    tool = await create_tool(
        async_client,
        slug="null-tool",
        name="空值工具",
        tags=["keep"],
        topic_ids=[topic["id"]],
        status="pending",
    )

    resp = await async_client.put(
        f"/api/v1/tools/{tool['id']}",
        json={"status": None, "tags": None, "languages": None, "review_score": None, "topic_ids": None},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "pending"
    assert data["tags"] == ["keep"]
    assert data["topic_ids"] == [topic["id"]]


async def test_update_tool_can_clear_description(async_client):
    """description 为可空字段, 显式 null 应能清空。"""
    tool = await create_tool(async_client, slug="desc", name="描述", description="原描述")
    resp = await async_client.put(f"/api/v1/tools/{tool['id']}", json={"description": None})
    assert resp.status_code == 200, resp.text
    assert resp.json()["description"] is None


async def test_update_tool_sets_review_and_timestamp(async_client):
    """人工复核: 写 review_score 自动补 reviewed_at, 且不覆盖 AI 分。"""
    tool = await create_tool(async_client, slug="reviewed", name="已复核", ai_score=900)

    resp = await async_client.put(f"/api/v1/tools/{tool['id']}", json={"review_score": 780, "reviewed_by": "alice"})

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["review_score"] == 780
    assert data["reviewed_by"] == "alice"
    assert data["reviewed_at"] is not None
    # 复核分是校准用的, 绝不能改写排序键
    assert data["ai_score"] == 900


async def test_update_tool_can_clear_review(async_client):
    """review_score 显式 null = 撤销复核, 三列必须一起清空(不留半截状态)。"""
    tool = await create_tool(async_client, slug="unreview", name="撤销复核")
    await async_client.put(f"/api/v1/tools/{tool['id']}", json={"review_score": 700, "reviewed_by": "bob"})

    resp = await async_client.put(f"/api/v1/tools/{tool['id']}", json={"review_score": None})

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["review_score"] is None
    assert data["reviewed_at"] is None
    assert data["reviewed_by"] is None


async def test_review_score_out_of_range_is_422(async_client):
    tool = await create_tool(async_client, slug="bad-review", name="越界复核")
    resp = await async_client.put(f"/api/v1/tools/{tool['id']}", json={"review_score": 1001})
    assert resp.status_code == 422


async def test_list_tools_orders_by_ai_score(async_client):
    """列表排序键是 ai_score DESC, 不再是人工 sort_order。"""
    await create_tool(async_client, slug="score-low", name="低分", ai_score=100)
    await create_tool(async_client, slug="score-high", name="高分", ai_score=900)

    resp = await async_client.get("/api/v1/tools")

    assert [item["slug"] for item in resp.json()] == ["score-high", "score-low"]


async def test_create_tool_primary_topic_must_be_in_topic_ids(async_client):
    """primary_topic_id 不在 topic_ids 里 -> 422(Pydantic 模型级校验)。"""
    topic = await create_topic(async_client, slug="topic", name="主题")
    resp = await async_client.post(
        "/api/v1/tools",
        json={**_MINIMAL, "slug": "orphan-primary", "topic_ids": [], "primary_topic_id": topic["id"]},
    )
    assert resp.status_code == 422


async def test_update_tool_primary_topic_must_be_in_topic_ids(async_client):
    """ToolUpdate 没有模型级校验, 由端点自己拦成 400。"""
    topic = await create_topic(async_client, slug="topic", name="主题")
    tool = await create_tool(async_client, slug="upd-primary", name="改主主题")
    resp = await async_client.put(
        f"/api/v1/tools/{tool['id']}",
        json={"topic_ids": [], "primary_topic_id": topic["id"]},
    )
    assert resp.status_code == 400


async def test_update_tool_replaces_topic_ids(async_client):
    topic_a = await create_topic(async_client, slug="topic-a", name="A")
    topic_b = await create_topic(async_client, slug="topic-b", name="B")
    tool = await create_tool(async_client, slug="multi-topic", name="多主题", topic_ids=[topic_a["id"]])

    resp = await async_client.put(f"/api/v1/tools/{tool['id']}", json={"topic_ids": [topic_b["id"]]})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["topic_ids"] == [topic_b["id"]]
    assert data["primary_topic_id"] == topic_b["id"]


async def test_nested_topic_tool_count(async_client):
    """工具响应里嵌套主题的 tool_count 必须是真实值, 不能停在默认 0。"""
    topic = await create_topic(async_client, slug="count-topic", name="嵌套计数")
    await create_tool(
        async_client,
        slug="pub-in-topic",
        name="已发布",
        topic_ids=[topic["id"]],
        status="published",
        links=[{"url": "https://pub-in-topic.example.com"}],
    )
    draft = await create_tool(async_client, slug="draft-in-topic", name="草稿", topic_ids=[topic["id"]])

    resp = await async_client.get(f"/api/v1/tools/{draft['id']}")
    assert resp.status_code == 200
    nested = next(t for t in resp.json()["topics"] if t["id"] == topic["id"])
    assert nested["tool_count"] == 1


async def test_create_helper_published_tool_can_take_links(async_client):
    """工厂建 published 工具时链接随 create 一起落库, 且能立刻被所有端点读到。"""
    tool = await create_tool(
        async_client,
        slug="helper-pub",
        name="工厂发布",
        status="published",
        links=[{"url": "https://helper.example.com"}],
    )
    assert tool["status"] == "published"
    assert tool["published_at"] is not None

    link = await create_link(async_client, tool["id"], url="https://helper-2.example.com")
    assert link["tool_id"] == tool["id"]

    resp = await async_client.get(f"/api/v1/tools/{tool['id']}/links")
    assert len(resp.json()) == 2


async def test_create_tool_with_nonexistent_topic_is_rolled_back(async_client):
    """建工具时给了不存在的主题 id: 400, 且工具行不能残留(同一事务要回滚)。"""
    resp = await async_client.post("/api/v1/tools", json={**_MINIMAL, "slug": "ghost-topic", "topic_ids": [99999]})
    assert resp.status_code == 400, resp.text
    assert "99999" in resp.json()["detail"]

    resp = await async_client.get("/api/v1/tools")
    assert resp.json() == []


async def test_update_tool_with_nonexistent_topic_rejected(async_client):
    tool = await create_tool(async_client, slug="upd-ghost", name="更新幽灵主题")
    resp = await async_client.put(f"/api/v1/tools/{tool['id']}", json={"topic_ids": [99999]})
    assert resp.status_code == 400, resp.text
    assert "99999" in resp.json()["detail"]

    # 归属没有被改动
    resp = await async_client.get(f"/api/v1/tools/{tool['id']}")
    assert resp.json()["topic_ids"] == []


async def test_update_tool_primary_topic_only(async_client):
    """只传 primary_topic_id(不带 topic_ids): 目标必须已是该工具的主题。"""
    topic_a = await create_topic(async_client, slug="topic-a", name="A")
    topic_b = await create_topic(async_client, slug="topic-b", name="B")
    tool = await create_tool(
        async_client,
        slug="only-primary",
        name="只换主主题",
        topic_ids=[topic_a["id"], topic_b["id"]],
        primary_topic_id=topic_a["id"],
    )

    resp = await async_client.put(f"/api/v1/tools/{tool['id']}", json={"primary_topic_id": topic_b["id"]})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["primary_topic_id"] == topic_b["id"]
    assert data["topic_ids"] == [topic_b["id"], topic_a["id"]]


async def test_update_tool_primary_topic_only_must_be_existing(async_client):
    topic_a = await create_topic(async_client, slug="topic-a", name="A")
    topic_b = await create_topic(async_client, slug="topic-b", name="B")
    tool = await create_tool(async_client, slug="bad-primary", name="坏主主题", topic_ids=[topic_a["id"]])

    resp = await async_client.put(f"/api/v1/tools/{tool['id']}", json={"primary_topic_id": topic_b["id"]})
    assert resp.status_code == 400


async def test_filter_by_unknown_topic_returns_empty(async_client):
    await create_tool(async_client, slug="t1", name="T1")
    resp = await async_client.get("/api/v1/tools?topic_id=99999")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_create_tool_accepts_audit_date_and_clears_it(async_client):
    """last_access_check_at 是外部事实日期: 可写, 也可以显式 null 清空(见 keep_none)。"""
    resp = await async_client.post(
        "/api/v1/tools",
        json={
            **_MINIMAL,
            "slug": "dated",
            "name": "带日期",
            "last_access_check_at": "2026-08-01",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["last_access_check_at"] == "2026-08-01"

    resp = await async_client.put(f"/api/v1/tools/{data['id']}", json={"last_access_check_at": None})
    assert resp.status_code == 200, resp.text
    assert resp.json()["last_access_check_at"] is None
