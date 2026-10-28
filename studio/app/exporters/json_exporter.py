"""导出器:把 MySQL 里的数据导出成 studio/schema/*.data.jsonc 定义的标准格式。

产物是【两个文件】:
    topics-{env}.json  主题列表(顶层数组)
    tools-{env}.json   工具列表(顶层数组)
prod 下额外同步一份无后缀的 topics.json / tools.json 给前端。

所有成员规则与排序都照 studio/sql/schema.sql 的【导出投影】实现,改动前先读那一段。
最要紧的两条:
  1. tools[] 成员 = status='published' 且【存在 active 链接】——少这条就会导出死链
  2. tools[].topics[] 取的是 xg_topic.slug,不是 xg_tool_topic.topic_id(那是 BIGINT)
"""

import asyncio
import json
import logging
import os
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models import LinkStatus, Pricing, Tool, ToolLink, ToolStatus, ToolTopic, Topic, TopicStatus
from app.schemas.common import ExportResponse

logger = logging.getLogger(__name__)

# 导出条目是逐字段拼出来的(可选字段按 NULL 语义【省略键】而不是输出 null, 见
# 文件头的规则), 所以结构上就是松散的 dict。取个名字只是让签名读起来仍然是
# "主题列表 / 工具列表", 别把它当成有保证的 schema —— 形状的权威定义在
# schema/topics.data.jsonc 与 schema/tools.data.jsonc。
type ExportItem = dict[str, Any]

DEFAULT_TOPIC_ICON = "📦"
UNCATEGORIZED_SLUG = "misc"
UNCATEGORIZED_NAME = "未分类"
_VALID_PRICINGS = frozenset(p.value for p in Pricing)


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


def _write_text_atomic(path: Path, content: str) -> None:
    """原子写入: 先写同目录临时文件再 os.replace, 避免中途失败留下被截断的 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with open(fd, "w", encoding="utf-8") as f:
            f.write(content)
        # mkstemp 建出来是 0600, 直接 replace 会让产物只有写入者可读 —— 这两个 JSON 是给
        # 前端构建 / 静态服务读的, 固定成 0644(与 web/data 下的其他文件一致)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _invalid_reason(row: Tool, url: str) -> str | None:
    """校验导出格式的必填字段, 返回问题描述(合法则为 None)。

    只处理"值能表达、但内容不合法"的行(空 slug / 空 tagline / 空 url / 空 languages),
    这类行跳过即可, 不值得为它中断整次导出。

    pricing 这一条是兜底: 枚举列由 ORM 在【读取时】校验(见 app/models._enum_column),
    读到枚举外的值会在取数阶段就抛 LookupError, 根本走不到这里; 留着它是为了覆盖
    None 这类不经枚举校验的脏值。
    """
    if _blank(row.slug) or _blank(row.name):
        return "slug/name 为空"
    if _blank(row.tagline):
        return "tagline 为空"
    if _blank(url):
        return "url 为空"
    if row.pricing not in _VALID_PRICINGS:
        return f"pricing 非法: {row.pricing!r}"
    if not row.languages:
        return "languages 为空"
    return None


async def export_to_json(session: AsyncSession) -> ExportResponse:
    settings = get_settings()

    try:
        topics, topic_skips = await _fetch_topics(session)
        tools, tool_skips = await _fetch_tools(session)
    except LookupError as exc:
        # 枚举取值越界: 读库读到脏值, 或绑定值不在枚举里(schema.sql 已经没有 ENUM/CHECK,
        # 值域只由 app 侧保证)。这里刻意不兜: 放它进产物会让前端整体校验失败, 比导出
        # 中断更难收拾。logger.exception 而不是 .error: 要同时保住"非法值 + 允许值"
        # 和读取路径的堆栈(同包的 __main__ 也是这么做的)。
        logger.exception("枚举取值越界, 导出中断: %s", exc)
        raise

    skips = topic_skips + tool_skips
    if skips:
        # 逐行 skip 的 warning 散在日志里, 容易被当成噪音忽略; 这里给一条能直接进监控的汇总
        logger.warning("本次导出跳过 %d 行: %s", sum(skips.values()), dict(skips))

    _ensure_uncategorized(topics, tools)
    _fill_tool_counts(topics, tools)

    topics_content = json.dumps(topics, ensure_ascii=False, indent=2) + "\n"
    tools_content = json.dumps(tools, ensure_ascii=False, indent=2) + "\n"

    paths = settings.export_paths()
    await asyncio.to_thread(_write_text_atomic, paths["topics"], topics_content)
    await asyncio.to_thread(_write_text_atomic, paths["tools"], tools_content)

    synced_frontend = False
    if settings.app_env == "prod":
        frontend_paths = settings.export_paths(frontend_names=True)
        await asyncio.to_thread(_write_text_atomic, frontend_paths["topics"], topics_content)
        await asyncio.to_thread(_write_text_atomic, frontend_paths["tools"], tools_content)
        synced_frontend = True
        logger.info("Synced frontend data source → %s / %s", frontend_paths["topics"], frontend_paths["tools"])
    else:
        logger.info("env=%s, skipped frontend sync (env artifact only)", settings.app_env)

    logger.info(
        "Exported %d topics, %d tools (skipped %d) → %s, %s",
        len(topics),
        len(tools),
        sum(skips.values()),
        paths["topics"],
        paths["tools"],
    )

    return ExportResponse(
        exported_at=datetime.now(UTC),
        # 只回文件名: 完整路径留在服务端日志里(见 ExportResponse.output_path 的注释)
        output_path=f"{paths['topics'].name}, {paths['tools'].name}",
        topics_count=len(topics),
        tools_count=len(tools),
        app_env=settings.app_env,
        synced_frontend=synced_frontend,
        skipped_count=sum(skips.values()),
        skipped_reasons=dict(skips),
    )


def _ensure_uncategorized(topics: list[ExportItem], tools: list[ExportItem]) -> None:
    """若存在回退到 misc 的工具, 保证主题列表里有这一项。

    正常情况下 misc 是 xg_topic 里一条真实种子行(见 schema.sql 第 5 节);
    这里只是兜底,避免种子被误删后导出物出现悬空引用。
    """
    referenced = any(UNCATEGORIZED_SLUG in t["topics"] for t in tools)
    exists = any(t["id"] == UNCATEGORIZED_SLUG for t in topics)
    if referenced and not exists:
        logger.warning("主题 %s 不在导出列表里, 已合成兜底项", UNCATEGORIZED_SLUG)
        topics.append(
            {
                "id": UNCATEGORIZED_SLUG,
                "name": UNCATEGORIZED_NAME,
                "icon": DEFAULT_TOPIC_ICON,
                "toolCount": 0,
            }
        )


def _fill_tool_counts(topics: list[ExportItem], tools: list[ExportItem]) -> None:
    """按【已导出的 tools[]】就地聚合 toolCount。

    刻意不另跑一条 SQL:口径必须和最终产物逐字一致,从同一个列表里数出来
    是唯一能保证不出现"导航徽标 12 / 主题页 11"的做法。
    """
    counts: Counter[str] = Counter()
    for tool in tools:
        for topic_slug in tool["topics"]:
            counts[topic_slug] += 1
    for topic in topics:
        topic["toolCount"] = counts.get(topic["id"], 0)


async def _fetch_topics(session: AsyncSession) -> tuple[list[ExportItem], Counter[str]]:
    stmt = select(Topic).where(Topic.status == TopicStatus.ACTIVE).order_by(Topic.sort_order.desc(), Topic.id)
    rows = (await session.execute(stmt)).scalars().all()

    topics: list[ExportItem] = []
    skipped: Counter[str] = Counter()
    for row in rows:
        if _blank(row.slug) or _blank(row.name):
            logger.warning("跳过主题 id=%s: slug/name 为空", row.id)
            skipped["主题 slug/name 为空"] += 1
            continue
        item: ExportItem = {
            "id": row.slug,
            "name": row.name,
            "icon": row.icon or DEFAULT_TOPIC_ICON,
        }
        # 可选字段为 NULL 时【省略键】,不输出 null(见 schema.sql 的 NULL 语义)
        if row.description:
            item["description"] = row.description
        topics.append(item)
    return topics, skipped


def _sorted_links(links: list[ToolLink]) -> list[ToolLink]:
    """active 链接,按 sort_order DESC, id ASC。

    排序只做一次并复用:url 选主链接、links[] 排除被选中的那条,都基于同一个列表,
    否则"哪条是主链接"在两处会有两种答案。
    """
    return sorted(
        (lnk for lnk in links if lnk.status == LinkStatus.ACTIVE),
        key=lambda lnk: (-lnk.sort_order, lnk.id),
    )


async def _fetch_tools(session: AsyncSession) -> tuple[list[ExportItem], Counter[str]]:
    # 两个 selectinload 把 links / tool_topics(+topic) 各用一条 IN 查询取回:
    # 循环里再碰关系属性就是 N+1,而且异步 session 惰性加载会直接抛 MissingGreenlet
    stmt = (
        select(Tool)
        .options(
            selectinload(Tool.links),
            selectinload(Tool.tool_topics).selectinload(ToolTopic.topic),
        )
        .where(Tool.status == ToolStatus.PUBLISHED)
        .order_by(Tool.ai_score.desc(), Tool.published_at.desc(), Tool.id)
    )
    rows = (await session.execute(stmt)).scalars().all()

    # 未评分的已发布工具 ai_score=0,会静默沉到列表最底。导出不阻断(缺分数不该
    # 让整站没数据),但要留下能搜到的线索。
    if unscored := [row.slug for row in rows if row.ai_score_at is None]:
        logger.warning("有 %d 个已发布工具还没评分,会排在列表末尾: %s", len(unscored), unscored[:5])

    tools: list[ExportItem] = []
    skipped: Counter[str] = Counter()
    for row in rows:
        active_links = _sorted_links(row.links)
        # 投影里的"取不到主链接就回退首个 active 链接"包含【取到了但值不可用】:
        # url 为空的行(直连改库才会出现)既不能当 url 也不能进 links[],
        # 否则产物里会出现空 URL,前端构建会整体失败
        usable = [lnk for lnk in active_links if not _blank(lnk.url)]
        if not usable:
            logger.warning("跳过工具 id=%s slug=%s: 无可用链接(无 active 链接或归一化 URL 为空)", row.id, row.slug)
            skipped["工具无可用链接"] += 1
            continue

        primary = next((lnk for lnk in usable if lnk.is_primary), None)
        url_link = primary or usable[0]

        if reason := _invalid_reason(row, url_link.url):
            logger.warning("跳过工具 id=%s: %s", row.id, reason)
            skipped[f"工具 {reason}"] += 1
            continue

        # topics[0] 即主主题:is_primary DESC → sort_order DESC → topic_id ASC
        topic_slugs = [
            tt.topic.slug
            for tt in sorted(
                row.tool_topics,
                key=lambda tt: (not tt.is_primary, -tt.sort_order, tt.topic_id),
            )
            if tt.topic is not None and tt.topic.status == TopicStatus.ACTIVE
        ]

        item: ExportItem = {
            "id": row.slug,
            "name": row.name,
            "tagline": row.tagline,
            "url": url_link.url,
            "topics": topic_slugs or [UNCATEGORIZED_SLUG],
            "tags": list(row.tags or []),
            "pricing": str(row.pricing),
            "openSource": bool(row.is_open_source),
            "origin": str(row.origin),
            "access": str(row.access),
            "languages": list(row.languages or []),
            "featured": bool(row.is_featured),
        }
        if row.description:
            item["description"] = row.description
        if row.published_at:
            item["publishedAt"] = row.published_at.strftime("%Y-%m-%d")
        # lastUpdatedAt 取【审计列】updated_at(改库时间), 不是"工具自身在上游的更新日期"
        # ——那个字段(原 xg_tool.last_updated_at)没有任何消费者, 已从库里删掉。
        # updated_at 是 NOT NULL, 所以这个键【永远存在】, 不适用"NULL 时省略键"的规则。
        item["lastUpdatedAt"] = row.updated_at.strftime("%Y-%m-%d")

        # 次要链接:排除【已被选作 url 的那一条】——否则当 url 回退到某个
        # is_primary=0 的链接时,同一个 URL 会在工具对象里出现两次
        secondary = [lnk for lnk in usable if not lnk.is_primary and lnk.id != url_link.id]
        if secondary:
            item["links"] = [{"label": str(lnk.label), "url": lnk.url} for lnk in secondary]

        tools.append(item)

    return tools, skipped
