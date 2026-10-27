"""主题端点。

工具数计数走 app.utils.db.published_tool_counts, 口径必须和 schema.sql 的
【导出投影】逐字一致(status='published' 且存在 active 链接), 否则会出现
"导航徽标 12 / 主题页 11"。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.endpoints.tools import hydrate_tools
from app.core.deps import DbSession
from app.core.security import require_write
from app.models import Tool, ToolTopic, Topic, TopicStatus
from app.schemas.models import ToolResponse, TopicCountResponse, TopicCreate, TopicResponse, TopicUpdate
from app.utils.db import check_unique, drop_none, published_tool_counts

router = APIRouter()


async def _published_tool_count(db: AsyncSession, topic_id: int) -> int:
    """该主题下【会进导出】的工具数, 与 /tool-count 端点语义一致."""
    return (await published_tool_counts(db, {topic_id})).get(topic_id, 0)


@router.get("", response_model=list[TopicResponse])
async def list_topics(
    response: Response,
    db: DbSession,
    status_filter: TopicStatus | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> list[Topic]:
    base = select(Topic)
    if status_filter is not None:
        base = base.where(Topic.status == status_filter)

    # 分页端点必须给出总数, 否则调用方无从知道还有没有下一页(与 /tools 的
    # X-Total-Count 保持同一套约定)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0

    stmt = base.order_by(Topic.sort_order.desc(), Topic.id).offset((page - 1) * page_size).limit(page_size)
    topics = list((await db.execute(stmt)).scalars().all())

    # 计数一次性批量取: 逐条查会变成 N+1
    count_map = await published_tool_counts(db, [t.id for t in topics])
    for topic in topics:
        topic.tool_count = count_map.get(topic.id, 0)
    response.headers["X-Total-Count"] = str(total)
    return topics


@router.get("/{topic_id}", response_model=TopicResponse)
async def get_topic(topic_id: int, db: DbSession) -> Topic:
    topic = await db.get(Topic, topic_id)
    if not topic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found")
    topic.tool_count = await _published_tool_count(db, topic_id)
    return topic


@router.get("/{topic_id}/tools", response_model=list[ToolResponse])
async def list_topic_tools(
    topic_id: int,
    response: Response,
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> list[Tool]:
    """该主题下的工具。

    这里【不过滤 status】——这是后台接口,编辑要能看到 draft/pending 的归属;
    和 /tool-count 的口径(只数会进导出的)刻意不同,别拿它当页面上那个徽标。
    """
    if not await db.get(Topic, topic_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found")

    # 总数按【归属关系】数, 与下面的过滤条件逐个对齐, 不跟 /tool-count 的导出口径混
    total = (
        await db.execute(select(func.count()).select_from(ToolTopic).where(ToolTopic.topic_id == topic_id))
    ).scalar() or 0

    stmt = (
        select(Tool)
        .join(ToolTopic, ToolTopic.tool_id == Tool.id)
        .where(ToolTopic.topic_id == topic_id)
        .options(
            selectinload(Tool.links),
            selectinload(Tool.tool_topics).selectinload(ToolTopic.topic),
        )
        .order_by(Tool.ai_score.desc(), Tool.published_at.desc(), Tool.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    response.headers["X-Total-Count"] = str(total)
    return await hydrate_tools(db, list(result.scalars().all()))


@router.post(
    "", response_model=TopicResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_write)]
)
async def create_topic(data: TopicCreate, db: DbSession) -> Topic:
    await check_unique(db, Topic, Topic.slug, data.slug, label="Slug")
    await check_unique(db, Topic, Topic.name, data.name, label="Topic name")

    topic = Topic(**data.model_dump())
    db.add(topic)
    # flush 是必需的: created_at/updated_at 由库端 server_default 生成, 不提前把
    # INSERT 发出去、refresh 取回来, 响应里就没有这两个字段(异步 session 也不会
    # 替我们惰性加载)。顺带让 uk_topic_slug / uk_topic_name 的并发冲突在这里
    # 就变成 409, 而不是拖到收尾提交时。
    await db.flush()
    await db.refresh(topic)
    topic.tool_count = 0
    return topic


@router.put("/{topic_id}", response_model=TopicResponse, dependencies=[Depends(require_write)])
async def update_topic(topic_id: int, data: TopicUpdate, db: DbSession) -> Topic:
    topic = await db.get(Topic, topic_id)
    if not topic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found")

    # 只有真正可空的字段允许显式 null 清空; icon 是 NOT NULL(有库端默认值),
    # 放它进 keep_none 只会把 null 写进库换一个 500
    update_data = drop_none(data.model_dump(exclude_unset=True), keep_none=("description",))
    if "slug" in update_data and update_data["slug"] != topic.slug:
        await check_unique(db, Topic, Topic.slug, update_data["slug"], exclude_id=topic_id, label="Slug")
    if "name" in update_data and update_data["name"] != topic.name:
        await check_unique(db, Topic, Topic.name, update_data["name"], exclude_id=topic_id, label="Topic name")

    for key, value in update_data.items():
        setattr(topic, key, value)

    await db.flush()
    await db.refresh(topic)
    topic.tool_count = await _published_tool_count(db, topic_id)
    return topic


@router.delete("/{topic_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_write)])
async def delete_topic(topic_id: int, db: DbSession) -> None:
    topic = await db.get(Topic, topic_id)
    if not topic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found")

    # xg_tool_topic.topic_id 的外键是 RESTRICT:主题下还有工具时直接删会报 500,
    # 在这里先拦成 409(要么重新归属,要么把主题改成 disabled 而不是删掉)
    count_stmt = select(func.count()).select_from(ToolTopic).where(ToolTopic.topic_id == topic_id)
    count = (await db.execute(count_stmt)).scalar() or 0
    if count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Topic has {count} tools (incl. unpublished). Remove or reassign them first.",
        )

    await db.delete(topic)
    # 上面那次计数只是快照, 挡不住"检查通过之后又有人挂了一条归属"。
    # 显式 flush 让真正的守卫(fk_tt_topic)在请求内执行, 撞上就由 main.py 的
    # IntegrityError 处理器回 409, 而不是静默半成功。
    await db.flush()


@router.get("/{topic_id}/tool-count", response_model=TopicCountResponse)
async def topic_tool_count(topic_id: int, db: DbSession) -> TopicCountResponse:
    if not await db.get(Topic, topic_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found")
    count = await _published_tool_count(db, topic_id)
    return TopicCountResponse(tool_count=count)
