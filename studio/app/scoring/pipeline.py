"""分类 + 评分流水线:取数 → N 次采样 → 校验聚合 → 写回。

设计约束(都不是随口定的):

1. **离线批处理,不进请求路径**。一次评分要几秒 + 花钱,同步接口撑不住;而且
   评分结果只影响排序,晚几分钟没有任何业务损失。
2. **只写 ai_* 列,不碰 review_* 列**。人工复核是人的领地,AI 写它等于自己给自己
   发合格证。这条在 _apply_judgement 里靠"只赋值 ai_ 前缀字段"实现。
3. **采样是并发的,写库是串行的**。模型调用可以并发(同一次 run 里互不依赖),
   但 AsyncSession 不是并发安全的;先 gather 完再逐条落库,避免出现"部分工具写成功、
   事务状态却已经乱了"的中间态。
4. **口语化地说**:先算一次全站先验(已有分数的中位数),整轮都用它。不边算边更新,
   否则同一批工具的结果会依赖处理顺序 —— 那是最难复现的一类 bug。
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from math import ceil
from statistics import mean
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Tool, ToolStatus, ToolTopic, Topic, TopicStatus
from app.scoring.aggregate import (
    SHRINKAGE_M,
    evidence_count,
    median_scores,
    normalize_dimension,
    prior_from_scores,
    score_confidence,
    shrink,
    to_score,
    weighted_raw,
)
from app.scoring.llm import Judge, Judgement, parse_judgement
from app.scoring.prompt import AnchorExample, TopicBrief, build_system_prompt, build_user_prompt
from app.scoring.rubric import DIMENSION_KEYS, RUBRIC_VERSION, version_tag

logger = logging.getLogger(__name__)

MAX_TOPICS_PER_TOOL = 3


@dataclass(slots=True)
class ScoringOptions:
    limit: int | None = None
    force: bool = False
    dry_run: bool = False
    apply_topics: bool = False
    samples: int = 3
    concurrency: int = 4
    statuses: tuple[ToolStatus, ...] = (ToolStatus.PUBLISHED,)


@dataclass(slots=True)
class ScoringReport:
    considered: int = 0
    scored: int = 0
    failed: int = 0
    topics_applied: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "considered": self.considered,
            "scored": self.scored,
            "failed": self.failed,
            "topics_applied": self.topics_applied,
            "errors": self.errors[:20],
        }


def _tool_payload(tool: Tool) -> dict[str, Any]:
    """给模型的输入。刻意不含 id/status/published_at(见 prompt.build_user_prompt)。"""
    return {
        "slug": tool.slug,
        "name": tool.name,
        "tagline": tool.tagline,
        "description": tool.description,
        "pricing": str(tool.pricing),
        "open_source": bool(tool.is_open_source),
        "origin": str(tool.origin),
        "access": str(tool.access),
        "languages": list(tool.languages or []),
        "tags": list(tool.tags or []),
        "topics": sorted(
            tt.topic.slug for tt in tool.tool_topics if tt.topic is not None and tt.topic.status == TopicStatus.ACTIVE
        ),
        "links": sorted(
            ({"label": str(link.label), "url": link.url} for link in tool.links if link.status == "active"),
            key=lambda item: item["url"],
        ),
    }


def aggregate_topics(judgements: list[Judgement], allowed: set[str]) -> list[dict[str, Any]]:
    """多次采样的主题投票 → 最终主题建议。

    规则(与 prompt 的"1~3 个、按相关度降序"对齐):
      - 只认白名单里的 slug(prompt 是软约束,这里是硬约束)
      - 半数以上采样都提到的主题才留下(N=3 即至少 2 票),避免单次幻觉带偏
      - 置信度 = 得票率 * 平均自评分,同时反映"模型多确定"和"模型多一致"
    """
    votes: dict[str, list[float]] = {}
    for judgement in judgements:
        for choice in judgement.topics:
            if choice.slug in allowed:
                votes.setdefault(choice.slug, []).append(choice.confidence)
    if not judgements:
        return []

    threshold = ceil(len(judgements) / 2)
    winners: list[dict[str, Any]] = [
        {
            "slug": slug,
            "confidence": round(mean(confidences) * len(confidences) / len(judgements), 4),
        }
        for slug, confidences in votes.items()
        if len(confidences) >= threshold
    ]
    winners.sort(key=lambda item: (-item["confidence"], item["slug"]))
    return winners[:MAX_TOPICS_PER_TOOL]


def _rejected_slugs(judgements: list[Judgement], allowed: set[str]) -> set[str]:
    return {choice.slug for judgement in judgements for choice in judgement.topics if choice.slug not in allowed}


def _build_breakdown(
    *,
    judgements: list[Judgement],
    median: dict[str, int],
    raw: float,
    evidence: int,
    prior: float,
    shrunk: float,
    confidence: float,
    topics: list[dict[str, Any]],
    model: str,
) -> dict[str, Any]:
    """可复算的快照。字段名就是 aggregate 里的符号,方便对着代码核对。"""
    first_reasons = {key: judgements[0].dimensions[key].reason for key in DIMENSION_KEYS}
    return {
        "rubric": RUBRIC_VERSION,
        "model": model,
        "samples": len(judgements),
        "dimensions": {
            key: {
                "score": median[key],
                "samples": [judgement.scores()[key] for judgement in judgements],
                "normalized": round(_normalized(median[key]), 4),
                "reason": first_reasons[key],
            }
            for key in DIMENSION_KEYS
        },
        "raw": round(raw, 4),
        "evidence": evidence,
        "prior": round(prior, 4),
        "m": SHRINKAGE_M,
        "shrunk": round(shrunk, 4),
        "confidence": round(confidence, 4),
        "topics": topics,
    }


def _normalized(score: int) -> float:
    return normalize_dimension(score)


async def _sample(
    judge: Judge,
    *,
    system: str,
    user: str,
    samples: int,
    semaphore: asyncio.Semaphore,
) -> tuple[list[Judgement], list[str]]:
    """并发跑 N 次采样并解析。单次失败不拖垮整条记录,但会记进 errors。"""
    async with semaphore:
        raw = await asyncio.gather(
            *(judge.complete(system=system, user=user) for _ in range(samples)),
            return_exceptions=True,
        )

    judgements: list[Judgement] = []
    errors: list[str] = []
    for item in raw:
        if isinstance(item, BaseException):
            errors.append(str(item))
            continue
        try:
            judgements.append(parse_judgement(item))
        except ValueError as exc:
            errors.append(str(exc))
    return judgements, errors


async def _load_anchors(session: AsyncSession, limit: int = 3) -> list[AnchorExample]:
    """取人工复核过的样本当 few-shot 锚点(按 review_score 分档 → 1/3/5)。

    只取 review_score 非空的行:那是唯一带人工判断的信号。没有复核样本时返回空列表,
    prompt 会退化成"无锚点"——能跑,但尺度只能靠模型自己,准确率会明显低一些。
    """
    stmt = (
        select(Tool)
        .where(Tool.review_score.is_not(None))
        .options(selectinload(Tool.links), selectinload(Tool.tool_topics).selectinload(ToolTopic.topic))
        .order_by(Tool.review_score.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()

    examples: list[AnchorExample] = []
    for row in rows:
        score = row.review_score or 0
        # 用分档而不是原值:review_score 是总分,反推不出六个维度;锚点只校准"高低档"
        tier = 1 if score <= 333 else (3 if score <= 666 else 5)
        topics = [tt.topic.slug for tt in row.tool_topics if tt.topic is not None]
        examples.append(AnchorExample(tool=_tool_payload(row), topics=topics or ["misc"], tier=tier))
    return examples


async def _apply_judgement(
    session: AsyncSession,
    *,
    tool: Tool,
    judgements: list[Judgement],
    topics: list[dict[str, Any]],
    prior: float,
    model: str,
) -> int:
    """写回 ai_* 列(不 commit)。返回最终 ai_score,方便 dry-run 打印。

    只赋值 ai_ 前缀的字段:review_score / reviewed_at / reviewed_by 是人的数据,
    AI 管线碰它一次,"人工复核"这个词就废了。
    """
    median = median_scores([judgement.scores() for judgement in judgements])
    raw = weighted_raw(median)
    active_links = [link for link in tool.links if str(link.status) == "active"]
    evidence = evidence_count(
        has_description=bool((tool.description or "").strip()),
        tag_count=len(tool.tags or []),
        topic_count=len([tt for tt in tool.tool_topics if tt.topic is not None]),
        link_count=len(active_links),
    )
    shrunk = shrink(raw, evidence, prior)
    confidence = score_confidence([judgement.scores() for judgement in judgements])
    score = to_score(shrunk)

    tool.ai_score = score
    tool.ai_score_confidence = Decimal(str(round(confidence, 2)))
    tool.ai_score_breakdown = _build_breakdown(
        judgements=judgements,
        median=median,
        raw=raw,
        evidence=evidence,
        prior=prior,
        shrunk=shrunk,
        confidence=confidence,
        topics=topics,
        model=model,
    )
    tool.ai_score_version = version_tag(model)
    tool.ai_score_at = await session.scalar(select(func.current_timestamp()))
    tool.ai_topics = topics
    return score


async def _replace_topics(session: AsyncSession, tool: Tool, slugs: list[str], slug_to_id: dict[str, int]) -> bool:
    """用 AI 建议整体替换主题归属。

    只在 --apply-topics 时调用,而且刻意不复用 endpoints/tools.py 的
    replace_tool_topics:那个函数带着 HTTPException 和行锁语义,是给在线请求用的;
    这里是一个单事务批处理,删干净再按顺序插入就够了(第一条即主主题)。
    """
    ids = [slug_to_id[slug] for slug in slugs if slug in slug_to_id]
    if not ids:
        # 分类没跑出有效结果时【不要清空原有归属】——把人工整理好的主题删成空,
        # 只为了等一次失败的 AI 结果,是纯粹的倒退。
        return False
    await session.execute(delete(ToolTopic).where(ToolTopic.tool_id == tool.id))
    # 先 flush 再插:bulk DELETE 之后同一事务里插入同主键的行,不 flush 会让
    # identity map 里同时存在"待删的旧行"和"待插的新行"
    await session.flush()
    for index, topic_id in enumerate(ids):
        session.add(ToolTopic(tool_id=tool.id, topic_id=topic_id, is_primary=index == 0, sort_order=0))
    return True


async def run_scoring(
    session: AsyncSession,
    judge: Judge,
    options: ScoringOptions,
    *,
    model_name: str = "unknown",
) -> ScoringReport:
    """跑一轮评分。不 commit —— 由调用方决定(dry-run 就不 commit)。"""
    report = ScoringReport()

    topics = list(
        (
            await session.execute(
                select(Topic).where(Topic.status == TopicStatus.ACTIVE).order_by(Topic.sort_order.desc(), Topic.id)
            )
        )
        .scalars()
        .all()
    )
    topic_briefs = [TopicBrief(slug=t.slug, name=t.name, description=t.description) for t in topics]
    slug_to_id = {t.slug: t.id for t in topics}
    allowed = set(slug_to_id)

    anchors = await _load_anchors(session)
    if not anchors:
        logger.warning("没有人工复核样本(review_score 非空),评分尺度只能靠模型自身,建议先复核 10~30 条")

    system = build_system_prompt(topic_briefs, anchors)

    stmt = (
        select(Tool)
        .options(
            selectinload(Tool.links),
            selectinload(Tool.tool_topics).selectinload(ToolTopic.topic),
        )
        .where(Tool.status.in_(options.statuses))
        .order_by(Tool.id)
    )
    if not options.force:
        stmt = stmt.where(Tool.ai_score_at.is_(None))
    if options.limit is not None:
        stmt = stmt.limit(options.limit)

    tools = list((await session.execute(stmt)).scalars().all())
    report.considered = len(tools)
    if not tools:
        logger.info("没有需要评分的工具(force=%s, limit=%s)", options.force, options.limit)
        return report

    prior = prior_from_scores(
        list((await session.execute(select(Tool.ai_score).where(Tool.ai_score_at.is_not(None)))).scalars().all())
    )
    logger.info(
        "开始评分: %d 个工具, 每个采样 %d 次, 并发 %d, 先验 %.4f",
        len(tools),
        options.samples,
        options.concurrency,
        prior,
    )

    semaphore = asyncio.Semaphore(options.concurrency)
    payloads = [_tool_payload(tool) for tool in tools]
    sampled = await asyncio.gather(
        *(
            _sample(
                judge,
                system=system,
                user=build_user_prompt(payload),
                samples=options.samples,
                semaphore=semaphore,
            )
            for payload in payloads
        )
    )

    rejected: Counter[str] = Counter()
    for tool, (judgements, errors) in zip(tools, sampled, strict=True):
        if not judgements:
            report.failed += 1
            report.errors.append(f"{tool.slug}: {'; '.join(errors[:2]) or '全部采样失败'}")
            logger.error("工具 %s 评分失败: %s", tool.slug, "; ".join(errors[:2]))
            continue

        if unknown := _rejected_slugs(judgements, allowed):
            rejected.update(unknown)
            logger.warning("工具 %s 返回了清单外的 slug,已丢弃: %s", tool.slug, sorted(unknown))

        topics_for_tool = aggregate_topics(judgements, allowed)
        score = await _apply_judgement(
            session,
            tool=tool,
            judgements=judgements,
            topics=topics_for_tool,
            prior=prior,
            model=model_name,
        )
        report.scored += 1
        logger.info("工具 %s → %d 分, 主题 %s", tool.slug, score, [t["slug"] for t in topics_for_tool])

        if options.apply_topics and topics_for_tool:
            applied = await _replace_topics(session, tool, [t["slug"] for t in topics_for_tool], slug_to_id)
            if applied:
                report.topics_applied += 1

    if rejected:
        logger.warning("本轮被丢弃的清单外 slug(共 %d 次): %s", sum(rejected.values()), dict(rejected))

    return report
