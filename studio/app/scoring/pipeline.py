"""分类 + 评分流水线:选行 → N 次采样 → 校验聚合 → 写回。

设计约束(都不是随口定的):

1. **离线批处理,不进请求路径**。一次评分要几秒 + 花钱,同步接口撑不住;而且
   评分结果只影响排序,晚几分钟没有任何业务损失。
2. **只写 ai_* 列,不碰 review_*/authority_override**。人工数据是人的领地,AI 写它
   等于自己给自己发合格证。这条在 _apply_judgement 里靠"只赋值 ai_ 前缀字段"实现。
3. **采样是并发的,写库是串行的**。模型调用可以并发(同一次 run 里互不依赖),
   但 AsyncSession 不是并发安全的;先 gather 完再逐条落库,避免出现"部分工具写成功、
   事务状态却已经乱了"的中间态。
4. **先算一次全站先验(已有分数的中位数),整轮都用它**。不边算边更新,否则同一批
   工具的结果会依赖处理顺序 —— 那是最难复现的一类 bug。
5. **重算有五个理由**,优先级从高到低:force / 从未评分 / 口径变了 / 内容变了 /
   太久了。理由会记进报告,这样"为什么这批跑了 37 个"有据可查。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from math import ceil
from statistics import mean, median
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import LinkStatus, Tool, ToolStatus, ToolTopic, Topic, TopicStatus
from app.scoring.aggregate import (
    SHRINKAGE_M,
    authority_ratio,
    combine,
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
from app.scoring.rubric import DIMENSION_KEYS, RUBRIC_REVISION, RUBRIC_VERSION, version_tag

logger = logging.getLogger(__name__)

MAX_TOPICS_PER_TOOL = 3
# 权威度与质量分相差超过这个值就标记为"分歧",供人工复核。
# 0.35 大致相当于"authority 8 分但 quality 只有 4 成"这种组合 —— 在 gamma=0.5 下
# 这类工具名次几乎完全由权威度决定,值得人看一眼。
DIVERGENCE_THRESHOLD = 0.35
# 单次采样解析失败后最多再要几次。实测模型偶发把 authority 写进 dimensions 里
# (括号层级错),这种错误重抽一次基本就好了;不重试会让整条工具白跑。
MAX_PARSE_RETRIES = 2


@dataclass(slots=True)
class ScoringOptions:
    limit: int | None = None
    force: bool = False
    changed: bool = False
    stale_days: int | None = None
    outdated_version: bool = False
    dry_run: bool = False
    apply_topics: bool = False
    samples: int = 3
    concurrency: int = 4
    authority_weight: float = 0.50
    statuses: tuple[ToolStatus, ...] = (ToolStatus.PUBLISHED,)


@dataclass(slots=True)
class ScoringReport:
    scanned: int = 0
    considered: int = 0
    scored: int = 0
    failed: int = 0
    topics_applied: int = 0
    diverged: int = 0
    diverged_slugs: list[str] = field(default_factory=list)
    by_reason: Counter[str] = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "scanned": self.scanned,
            "considered": self.considered,
            "scored": self.scored,
            "failed": self.failed,
            "topics_applied": self.topics_applied,
            "diverged": self.diverged,
            "diverged_slugs": self.diverged_slugs[:5],
            "by_reason": dict(self.by_reason),
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
            ({"label": str(link.label), "url": link.url} for link in tool.links if link.status == LinkStatus.ACTIVE),
            key=lambda item: item["url"],
        ),
    }


def payload_digest(payload: dict[str, Any]) -> str:
    """评分输入的指纹(SHA-256)。

    用指纹而不是"更新时打个脏标记":后者要在每条写入路径上记得清标记,漏一处就永远
    不重算;而且这个项目里直连改库是常态。指纹是自愈的 —— 谁改的、从哪改的都认。
    sort_keys + 固定分隔符 保证同一份内容永远得到同一个 hash。
    """
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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


def _normalized(score: int) -> float:
    return normalize_dimension(score)


def _build_breakdown(
    *,
    judgements: list[Judgement],
    median_scores_by_dimension: dict[str, int],
    raw: float,
    evidence: int,
    prior: float,
    quality: float,
    confidence: float,
    topics: list[dict[str, Any]],
    model: str,
    authority_ai: int,
    authority_effective: int,
    authority_weight: float,
) -> dict[str, Any]:
    """可复算的快照。字段名就是 aggregate 里的符号,方便对着代码核对。

    `quality` 是【未经权威度调整】的那部分,authority_override 改完之后可以拿它
    直接重算 ai_score,不需要再调一次模型。
    """
    first_reasons = {key: judgements[0].dimensions[key].reason for key in DIMENSION_KEYS}
    return {
        "rubric": RUBRIC_VERSION,
        "rubric_revision": RUBRIC_REVISION,
        "model": model,
        "samples": len(judgements),
        "dimensions": {
            key: {
                "score": median_scores_by_dimension[key],
                "samples": [judgement.scores()[key] for judgement in judgements],
                "normalized": round(_normalized(median_scores_by_dimension[key]), 4),
                "reason": first_reasons[key],
            }
            for key in DIMENSION_KEYS
        },
        "raw": round(raw, 4),
        "evidence": evidence,
        "prior": round(prior, 4),
        "m": SHRINKAGE_M,
        "quality": round(quality, 4),
        "authority": {
            "ai": authority_ai,
            "effective": authority_effective,
            "reason": judgements[0].authority.reason,
        },
        "authority_weight": round(authority_weight, 4),
        # 两根轴的分歧:越大说明这个工具的名次越依赖"重不重要"而不是"好不好"
        "divergence": round(abs(authority_ratio(authority_effective) - quality), 4),
        "confidence": round(confidence, 4),
        "topics": topics,
    }


def _rescore_reason(
    tool: Tool,
    digest: str,
    options: ScoringOptions,
    current_version: str,
    now: datetime,
) -> str | None:
    """该不该重算,以及为什么。返回 None 表示跳过。"""
    if options.force:
        return "force"
    last_scored_at = tool.ai_score_at
    if last_scored_at is None or tool.ai_score_input_hash is None:
        return "new"
    if options.outdated_version and tool.ai_score_version != current_version:
        return "version"
    if options.changed and tool.ai_score_input_hash != digest:
        return "changed"
    if options.stale_days and last_scored_at < now - timedelta(days=options.stale_days):
        return "stale"
    return None


async def _one_sample(
    judge: Judge,
    *,
    system: str,
    user: str,
    semaphore: asyncio.Semaphore,
) -> tuple[Judgement | None, str | None]:
    """取一次可用采样:解析失败就重抽,最多 MAX_PARSE_RETRIES 次。

    重抽而不是"修补 JSON":结构错位的文本没法在不猜测的前提下修好,而一次重抽
    的成本远低于把错误分数写进库。
    """
    async with semaphore:
        last_error: str | None = None
        for _ in range(MAX_PARSE_RETRIES + 1):
            try:
                text = await judge.complete(system=system, user=user)
            except Exception as exc:  # 单次失败降级为"这条采样不可用"
                last_error = str(exc)
                continue
            try:
                return parse_judgement(text), None
            except ValueError as exc:
                last_error = str(exc)
        return None, last_error


async def _sample(
    judge: Judge,
    *,
    system: str,
    user: str,
    samples: int,
    semaphore: asyncio.Semaphore,
) -> tuple[list[Judgement], list[str]]:
    """并发跑 N 个采样槽位。单槽失败不拖垮整条记录,但会记进 errors。"""
    results = await asyncio.gather(
        *(_one_sample(judge, system=system, user=user, semaphore=semaphore) for _ in range(samples))
    )
    judgements = [judgement for judgement, _ in results if judgement is not None]
    errors = [error for _, error in results if error]
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
    authority_weight: float,
    digest: str,
) -> int:
    """写回 ai_* 列(不 commit)。返回最终 ai_score。

    只赋值 ai_ 前缀的字段:review_score / reviewed_* 是人的数据,authority_override
    也是人的数据。AI 只写"自己的建议"(ai_authority),绝不覆盖人工判断。
    """
    samples = [judgement.scores() for judgement in judgements]
    median_by_dimension = median_scores(samples)
    raw = weighted_raw(median_by_dimension)
    active_links = [link for link in tool.links if link.status == LinkStatus.ACTIVE]
    evidence = evidence_count(
        has_description=bool((tool.description or "").strip()),
        tag_count=len(tool.tags or []),
        topic_count=len([tt for tt in tool.tool_topics if tt.topic is not None]),
        link_count=len(active_links),
    )
    quality = shrink(raw, evidence, prior)
    confidence = score_confidence(samples)
    authority_ai = round(median([judgement.authority.score for judgement in judgements]))
    # 人工覆盖优先;覆盖值本身不参与"AI 建议"的统计,所以 ai_authority 仍写 AI 的判断
    authority_effective = tool.authority_override if tool.authority_override is not None else authority_ai
    score = to_score(combine(quality, authority_effective, authority_weight))

    tool.ai_score = score
    tool.ai_score_confidence = Decimal(str(round(confidence, 2)))
    tool.ai_score_breakdown = _build_breakdown(
        judgements=judgements,
        median_scores_by_dimension=median_by_dimension,
        raw=raw,
        evidence=evidence,
        prior=prior,
        quality=quality,
        confidence=confidence,
        topics=topics,
        model=model,
        authority_ai=authority_ai,
        authority_effective=authority_effective,
        authority_weight=authority_weight,
    )
    tool.ai_score_version = version_tag(model, authority_weight)
    tool.ai_score_at = await session.scalar(select(func.current_timestamp()))
    tool.ai_score_input_hash = digest
    tool.ai_authority = authority_ai
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
    rows = list((await session.execute(stmt)).scalars().all())
    report.scanned = len(rows)
    if not rows:
        logger.info("没有 published 工具,跳过")
        return report

    # 时间基准统一取【库的时钟】:ai_score_at 是库里写的 DATETIME,拿进程时钟去比,
    # 容器 UTC + 库 +08 时会整整差 8 小时,90 天的门槛会被提前触发或永远不触发。
    now = await session.scalar(select(func.now()))
    if not isinstance(now, datetime):
        raise RuntimeError("无法从数据库读取当前时间")
    current_version = version_tag(model_name, options.authority_weight)

    selected: list[tuple[Tool, dict[str, Any], str, str]] = []
    for tool in rows:
        payload = _tool_payload(tool)
        digest = payload_digest(payload)
        reason = _rescore_reason(tool, digest, options, current_version, now)
        if reason is None:
            continue
        selected.append((tool, payload, digest, reason))
        if options.limit is not None and len(selected) >= options.limit:
            break

    report.considered = len(selected)
    report.by_reason = Counter(reason for _, _, _, reason in selected)
    if not selected:
        logger.info(
            "没有需要评分的工具(force=%s, changed=%s, stale=%s)", options.force, options.changed, options.stale_days
        )
        return report

    prior = prior_from_scores(
        list((await session.execute(select(Tool.ai_score).where(Tool.ai_score_at.is_not(None)))).scalars().all())
    )
    logger.info(
        "开始评分: %d 个工具(扫描 %d), 每个采样 %d 次, 并发 %d, 先验 %.4f, 口径 %s",
        len(selected),
        report.scanned,
        options.samples,
        options.concurrency,
        prior,
        current_version,
    )

    semaphore = asyncio.Semaphore(options.concurrency)
    sampled = await asyncio.gather(
        *(
            _sample(
                judge,
                system=system,
                user=build_user_prompt(payload),
                samples=options.samples,
                semaphore=semaphore,
            )
            for _, payload, _, _ in selected
        )
    )

    rejected: Counter[str] = Counter()
    for (tool, _, digest, _), (judgements, errors) in zip(selected, sampled, strict=True):
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
            authority_weight=options.authority_weight,
            digest=digest,
        )
        report.scored += 1
        divergence = (tool.ai_score_breakdown or {}).get("divergence", 0.0)
        if isinstance(divergence, (int, float)) and divergence > DIVERGENCE_THRESHOLD:
            report.diverged += 1
            report.diverged_slugs.append(tool.slug)
        logger.info(
            "工具 %s → %d 分, 权威度 %s, 主题 %s",
            tool.slug,
            score,
            tool.ai_authority,
            [t["slug"] for t in topics_for_tool],
        )

        if options.apply_topics and topics_for_tool:
            applied = await _replace_topics(session, tool, [t["slug"] for t in topics_for_tool], slug_to_id)
            if applied:
                report.topics_applied += 1

    if rejected:
        logger.warning("本轮被丢弃的清单外 slug(共 %d 次): %s", sum(rejected.values()), dict(rejected))
    if report.diverged:
        logger.warning(
            "有 %d 个工具的权威度与质量判断相差 > %.2f,建议人工复核: %s",
            report.diverged,
            DIVERGENCE_THRESHOLD,
            report.diverged_slugs[:5],
        )

    return report
