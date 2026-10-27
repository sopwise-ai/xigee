"""评分管线的集成测试(需要 MySQL,与其余测试同一套门禁)。

纯函数测试在 tests/test_scoring.py(不连库,可 --noconftest 单独跑);这里只验
"真的写进库了吗"以及两条不能破的边界:

  1. AI 管线只能写 ai_* 列 —— review_score / reviewed_at / reviewed_by 必须原样不动
  2. --apply-topics 的整体替换要留下恰好一个主主题,且按 AI 给的顺序
"""

from __future__ import annotations

import json

from app.core.database import AsyncSessionLocal
from app.scoring.pipeline import ScoringOptions, run_scoring
from app.scoring.rubric import DIMENSION_KEYS, version_tag
from tests.conftest import create_tool, create_topic


class _FakeJudge:
    """回声判分器: 固定返回一份合法 JSON,不碰网络。"""

    def __init__(self, topics: list[str]) -> None:
        self._topics = topics
        self._payload = json.dumps(
            {
                "topics": [{"slug": slug, "confidence": 0.9} for slug in self._topics],
                "dimensions": {key: {"score": 4, "reason": "测试固定值"} for key in DIMENSION_KEYS},
                "summary": "集成测试",
            },
            ensure_ascii=False,
        )

    async def complete(self, *, system: str, user: str) -> str:
        return self._payload


async def test_pipeline_writes_ai_fields_without_touching_review(async_client):
    topic = await create_topic(async_client, slug="chat", name="对话")
    tool = await create_tool(
        async_client,
        slug="pipeline-tool",
        name="流水线工具",
        description="一个用于集成测试的对话工具。",
        tags=["a", "b", "c"],
        topic_ids=[topic["id"]],
        links=[{"url": "https://pipeline.example.com"}],
        status="published",
    )
    # 先落一条人工复核,用来证明 AI 管线不会覆盖它
    await async_client.put(f"/api/v1/tools/{tool['id']}", json={"review_score": 700, "reviewed_by": "alice"})
    before = (await async_client.get(f"/api/v1/tools/{tool['id']}")).json()

    async with AsyncSessionLocal() as session:
        report = await run_scoring(session, _FakeJudge(["chat"]), ScoringOptions(samples=1), model_name="fake-model")
        await session.commit()

    assert report.scored == 1
    assert report.failed == 0

    data = (await async_client.get(f"/api/v1/tools/{tool['id']}")).json()
    # 证据 3 条(描述/标签/主题) + 三维 4 分 → 收缩后约 0.65
    assert 600 <= data["ai_score"] <= 700
    assert data["ai_score_at"] is not None
    assert data["ai_score_version"] == version_tag("fake-model")
    assert data["ai_topics"][0]["slug"] == "chat"

    # 人工字段必须逐字不变
    assert data["review_score"] == before["review_score"] == 700
    assert data["reviewed_by"] == before["reviewed_by"] == "alice"
    assert data["reviewed_at"] == before["reviewed_at"]


async def test_pipeline_apply_topics_replaces_membership(async_client):
    old = await create_topic(async_client, slug="old-topic", name="旧主题")
    new = await create_topic(async_client, slug="new-topic", name="新主题")
    tool = await create_tool(
        async_client,
        slug="topic-move",
        name="换主题",
        topic_ids=[old["id"]],
        primary_topic_id=old["id"],
        links=[{"url": "https://move.example.com"}],
        status="published",
    )

    async with AsyncSessionLocal() as session:
        report = await run_scoring(
            session,
            _FakeJudge(["new-topic"]),
            ScoringOptions(samples=1, apply_topics=True),
            model_name="fake-model",
        )
        await session.commit()

    assert report.topics_applied == 1
    data = (await async_client.get(f"/api/v1/tools/{tool['id']}")).json()
    assert [item["slug"] for item in data["topics"]] == ["new-topic"]
    assert data["primary_topic_id"] == new["id"]
