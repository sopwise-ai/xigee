"""工具端点。

几个必须守住的坑(下面每处都有对应注释):
  1. status 迁移走 app.models.VALID_STATUS_TRANSITIONS —— draft→published 被拒,
     必须先经过 pending,否则库里那个"待审核"就只是装饰
  2. published_at 只在【首次】转 published 时写一次(日期取库的会话时钟):
     它记的是"收录进本站的日期",下架再上架也不该改写
  3. 每个工具【至多】一个主主题 / 一个主链接。schema.sql 精简后库层已经没有
     哨兵列和唯一索引了,这条不变量【只由 API 保证】,而"先清旧主、再设新主"
     这种三步 flush 本身挡不住并发(两个请求会同时读到"没有主"),所以真正
     的保证是 lock_tool_row 里的行锁,细节见该函数
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.deps import DbSession
from app.core.security import require_write
from app.models import (
    VALID_STATUS_TRANSITIONS,
    Tool,
    ToolLink,
    ToolStatus,
    ToolTopic,
    Topic,
)
from app.schemas.models import MAX_URL_LENGTH, ToolCreate, ToolResponse, ToolUpdate
from app.scoring.aggregate import recompute_score
from app.utils.db import check_unique, drop_none, published_tool_counts
from app.utils.url import InvalidURLError, normalize_url, url_hash_normalized

router = APIRouter()

# 新建时只允许出生为 draft/pending:published 必须走 pending 这一关,
# 而且"出生即 published"会绕过下面 published_at 的写入时机
_VALID_INITIAL_STATUSES = {ToolStatus.DRAFT, ToolStatus.PENDING}


def normalize_link_url(raw_url: str) -> tuple[str, str]:
    """把客户端给的原始 URL 收口成要落库的两件套: (url, url_hash)。

    url 就是【归一化之后】的串 —— xg_tool_link 只有这一列 URL, 库里不保留用户输入:
      url       normalize_url() 的结果(已满足 https、无尾斜杠、无 www.)
      url_hash  SHA-256(url), 只在同一工具内做唯一键

    这里是 URL 唯一的写入口: 三个写入点(单独建链接 / 改链接 / 建工具时带链接)都走它。
    任何一处绕过它, 未归一化的串就会被写进唯一键与导出都认的那一列。
    """
    try:
        normalized = normalize_url(raw_url)
    except InvalidURLError as exc:
        # schema 那层只能拦住非 http(s)/缺主机名(422); 端口非法这类要等归一化才暴露,
        # 所以在这里补一个 422(而不是让 main.py 的全局 InvalidURLError 处理器回 400)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    # 用 url_hash_normalized 而不是 url_hash(raw_url): 后者内部会再归一化一次,
    # 而它自己的文档要求"hash 与 normalized 必须来自同一次归一化"。
    # 另外这里补一个归一化后的长度校验: 长 URL 百分号编码后会膨胀
    # (一个汉字 1 字符 → 9 字符), 落库 VARCHAR(2048) 超长会报 1406(500)。
    if len(normalized) > MAX_URL_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"URL is too long after normalization (max {MAX_URL_LENGTH} characters)",
        )
    return normalized, url_hash_normalized(normalized)


async def load_tool(db: AsyncSession, tool_id: int, *, for_update: bool = False) -> Tool | None:
    """按 id 取工具, 并把响应需要的两个关系一次取回。

    selectinload 是必需的:异步 session 里访问未加载的关系不会自动补一次查询,
    而是直接抛 MissingGreenlet。

    for_update=True 时主查询带 FOR UPDATE 锁住 xg_tool 行(关联子表由 selectin
    的独立 SELECT 取, 不会被锁)。它必须是本事务的【第一条】语句才有意义:
    普通 SELECT 一旦先跑, REPEATABLE READ 的快照就定在那一刻了。
    """
    stmt = (
        select(Tool)
        .options(
            selectinload(Tool.links),
            selectinload(Tool.tool_topics).selectinload(ToolTopic.topic),
        )
        .where(Tool.id == tool_id)
    )
    if for_update:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def lock_tool_row(db: AsyncSession, tool_id: int) -> None:
    """给 xg_tool 行加排他锁, 工具不存在则 404。

    库里【没有】"至多一个主主题 / 一个主链接"的唯一索引(schema.sql 精简时删掉了
    哨兵列), 这个不变量完全落在 API 身上。"先清旧主再设新主 + flush"只能保证
    单个请求内部是自洽的: 两个并发请求可以同时读到"这个工具没有主主题", 然后
    各自插一条 is_primary=1 —— 谁都不会撞索引, 库里就留下两个主主题, 导出时
    topics[0] 是哪一个全看排序。

    xg_tool 行是所有主题归属/链接的公共父行, 拿它当【每个工具的写锁】:
    InnoDB 的 SELECT ... FOR UPDATE 会让同一工具的并发写请求在这里排队, 后来者
    等锁拿到时, 前一个事务已经提交, 后面按加锁读看到的就是【新状态】。
    加锁顺序统一是"先父行、再子行", 不会和 delete_tool(级联删除也先锁父行)
    交叉成死锁。
    """
    exists = (await db.execute(select(Tool.id).where(Tool.id == tool_id).with_for_update())).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found")


async def _tool_or_404(db: AsyncSession, tool_id: int) -> Tool:
    tool = await load_tool(db, tool_id)
    if not tool:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found")
    return tool


def ordered_tool_topics(rows: list[ToolTopic]) -> list[ToolTopic]:
    """主题归属的排序, 与 schema.sql【导出投影】逐字一致。

    is_primary DESC → sort_order DESC → topic_id ASC:导出 topics[0] 就是主主题。
    API 用同一个排序,否则"接口里看到的第一个主题"和"导出里的第一个主题"会是两个。
    """
    return sorted(rows, key=lambda tt: (not tt.is_primary, -tt.sort_order, tt.topic_id))


async def ordered_topic_ids(db: AsyncSession, tool_id: int) -> list[int]:
    """按上面的顺序取主题 id(只改归属、不需要整行对象时用)。"""
    stmt = select(ToolTopic).where(ToolTopic.tool_id == tool_id)
    rows = list((await db.execute(stmt)).scalars().all())
    return [tt.topic_id for tt in ordered_tool_topics(rows)]


async def hydrate_tools(db: AsyncSession, tools: list[Tool]) -> list[Tool]:
    """补齐 ToolResponse 里【不是 ORM 列】的字段。

    topic_ids / primary_topic_id / topics 都在 xg_tool_topic 里(is_primary 是每条
    关系自己的属性),这里摊平成响应字段;嵌套主题的 tool_count 一并填真实值——
    留着默认的 0 会让前端的主题徽标显示错的条数。
    """
    topic_ids = {tt.topic_id for tool in tools for tt in tool.tool_topics}
    counts = await published_tool_counts(db, topic_ids)
    for tool in tools:
        ordered = ordered_tool_topics(tool.tool_topics)
        tool.topics = [tt.topic for tt in ordered if tt.topic is not None]
        tool.topic_ids = [tt.topic_id for tt in ordered]
        tool.primary_topic_id = next((tt.topic_id for tt in ordered if tt.is_primary), None)
        for tt in ordered:
            if tt.topic is not None:
                tt.topic.tool_count = counts.get(tt.topic_id, 0)
    return tools


async def hydrate_tool(db: AsyncSession, tool: Tool) -> Tool:
    await hydrate_tools(db, [tool])
    return tool


async def _reload_tool(db: AsyncSession, tool_id: int) -> Tool:
    """写完之后按 id 重新取一遍再返回。

    改归属是直接操作 xg_tool_topic 行的,session 里已经加载的 tool_topics / links
    集合可能已经过期;异步 session 补不了惰性加载,所以显式 expire 再 selectinload。
    """
    db.expire_all()
    tool = await _tool_or_404(db, tool_id)
    return await hydrate_tool(db, tool)


async def replace_tool_topics(
    db: AsyncSession,
    tool_id: int,
    *,
    topic_ids: list[int],
    primary_topic_id: int | None = None,
) -> None:
    """整体替换一个工具的主题归属。

    主主题的确定顺序:
      1. 调用方明确给了 primary_topic_id 就用它
      2. 否则保留【原有的主主题】(只要它还在新集合里)——省略不等于要把它挪走
      3. 否则取新集合的第一个:库里已经没有唯一索引能保证"恰好一个主主题",
         零主主题时导出端会按 sort_order 兜底,工具的分节就会静默漂移

    这是"至多一个主主题"的唯一收口点, 两层保证缺一不可:
      - lock_tool_row: 把同一工具的并发写请求串行化(不变量靠 API 保证, 见该函数)
      - 下面三步的【加锁读 + 全量重算】: 最后一步会把该工具所有关联行的
        is_primary 重新算一遍, 所以并发写者即使在加锁前留下了脏的多主, 也会被修正
    """
    # 加锁必须在任何普通 SELECT 之前: REPEATABLE READ 的快照由本事务第一条
    # 一致性读决定, 先读后锁会看到加锁前的旧数据
    await lock_tool_row(db, tool_id)

    desired = list(dict.fromkeys(topic_ids))
    if primary_topic_id is not None and primary_topic_id not in desired:
        # 放过去的话第三步会把所有行都置成 0, 工具就"没有主主题"了 —— 静默漂移
        # 比报错难查得多。schema 层已经用 model_validator 拦过一遍, 这里是兜底。
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"primary_topic_id {primary_topic_id} is not in topic_ids",
        )

    if desired:
        found = set((await db.execute(select(Topic.id).where(Topic.id.in_(desired)))).scalars().all())
        # 主题不存在时外键 RESTRICT 会到 flush 时才报,500 不如提前拦成 400
        if invalid := set(desired) - found:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Topic IDs not found: {sorted(invalid)}",
            )

    # 加锁读归属行: 行锁只挡住别人, 本事务的快照可能仍停在加锁之前
    stmt = select(ToolTopic).where(ToolTopic.tool_id == tool_id).with_for_update()
    link_rows = list((await db.execute(stmt)).scalars().all())
    current = {row.topic_id: row for row in link_rows}
    previous_primary = next((row.topic_id for row in link_rows if row.is_primary), None)

    # 第一步: 摘掉旧主主题 + 删掉不再需要的归属,然后【立刻 flush】。
    # 刻意不依赖 SQLAlchemy 在一次 flush 内部的语句顺序(它取决于对象什么时候
    # 进入 unit of work), 分步 flush 让"任何一条语句执行完时库里都不会有两个主"
    # 这件事由我们控制, 而不是由 UOW 的实现细节决定。
    for topic_id, row in current.items():
        if topic_id not in desired:
            await db.delete(row)
        elif row.is_primary:
            row.is_primary = False
    await db.flush()

    if primary_topic_id is not None:
        primary = primary_topic_id
    elif previous_primary in desired:
        primary = previous_primary
    elif desired:
        primary = desired[0]
    else:
        primary = None

    # 第二步: 补上缺失的归属,先一律按非主主题插入,同样是为了不留中间态
    for topic_id in desired:
        if topic_id not in current:
            db.add(ToolTopic(tool_id=tool_id, topic_id=topic_id, is_primary=False, sort_order=0))
    await db.flush()

    # 第三步: 主主题只在这一步标,此时旧主主题早已落库为 0; 顺带把可能存在的
    # 脏数据(多主 / 主主题不在集合里)重算干净
    if primary is not None:
        for row in (await db.execute(stmt)).scalars().all():
            row.is_primary = row.topic_id == primary
    await db.flush()


@router.get("", response_model=list[ToolResponse])
async def list_tools(
    response: Response,
    db: DbSession,
    status_filter: ToolStatus | None = Query(None, alias="status"),
    topic_id: int | None = None,
    featured: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> list[Tool]:
    base = select(Tool)
    if status_filter is not None:
        base = base.where(Tool.status == status_filter)
    if topic_id is not None:
        base = base.join(ToolTopic, ToolTopic.tool_id == Tool.id).where(ToolTopic.topic_id == topic_id)
    if featured is not None:
        base = base.where(Tool.is_featured == featured)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = base.options(
        selectinload(Tool.links),
        selectinload(Tool.tool_topics).selectinload(ToolTopic.topic),
    )
    stmt = stmt.order_by(Tool.ai_score.desc(), Tool.published_at.desc(), Tool.id)
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(stmt)
    tools = list(result.scalars().all())
    response.headers["X-Total-Count"] = str(total)
    return await hydrate_tools(db, tools)


@router.get("/{tool_id}", response_model=ToolResponse)
async def get_tool(tool_id: int, db: DbSession) -> Tool:
    tool = await _tool_or_404(db, tool_id)
    return await hydrate_tool(db, tool)


@router.post(
    "", response_model=ToolResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_write)]
)
async def create_tool(data: ToolCreate, db: DbSession) -> Tool:
    # 先做完 payload 自身的校验再碰库: 非法输入不该产生任何查询
    initial_status = ToolStatus(data.status)
    if initial_status not in _VALID_INITIAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Initial status must be {ToolStatus.DRAFT} or {ToolStatus.PENDING}, got {initial_status}",
        )

    if sum(1 for link in data.links if link.is_primary) > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only one primary link allowed per tool",
        )

    # url_hash 是 (tool_id, url_hash) 唯一键的一半:同一次 payload 里两个不同的 URL
    # 归一化后可能撞成同一个 key,靠 500 兜底不如在这里拦成 400
    link_urls = [normalize_link_url(link.url) for link in data.links]
    link_hashes = [url_hash_value for _, url_hash_value in link_urls]
    if len(set(link_hashes)) != len(link_hashes):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duplicate URLs in links payload",
        )

    await check_unique(db, Tool, Tool.slug, data.slug, label="Slug")
    await check_unique(db, Tool, Tool.name, data.name, label="Tool name")

    tool = Tool(**data.model_dump(exclude={"links", "topic_ids", "primary_topic_id"}))
    db.add(tool)
    # 先 flush 拿到自增 id:下面的链接行与关联行都要用它
    await db.flush()

    for link_data, (normalized_url, url_hash_value) in zip(data.links, link_urls, strict=True):
        db.add(
            ToolLink(
                tool_id=tool.id,
                url=normalized_url,
                url_hash=url_hash_value,
                label=link_data.label,
                is_primary=link_data.is_primary,
                status=link_data.status,
                sort_order=link_data.sort_order,
            )
        )

    # 这里必须 flush 后拿 id 再传进去(而不是传 tool 对象):replace_tool_topics
    # 自己按 tool_id 查关联行,不依赖调用方有没有加载 tool_topics 集合
    await replace_tool_topics(db, tool.id, topic_ids=data.topic_ids, primary_topic_id=data.primary_topic_id)

    return await _reload_tool(db, tool.id)


@router.put("/{tool_id}", response_model=ToolResponse, dependencies=[Depends(require_write)])
async def update_tool(tool_id: int, data: ToolUpdate, db: DbSession) -> Tool:
    # 加锁读放最前面: 这个函数既要读 status 做迁移判断, 又要改主主题, 两者都不能
    # 基于加锁前的旧快照。锁的粒度是"一个工具", 后台逐条编辑不会成为瓶颈。
    tool = await load_tool(db, tool_id, for_update=True)
    if not tool:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found")

    # 只有真正可空的列允许显式 null 清空(description / access 复检日期 / 人工复核);
    # 其余 None 一律忽略——把 None 写进 NOT NULL 的列只会换来一个 500
    update_data = drop_none(
        data.model_dump(exclude_unset=True),
        keep_none=("description", "last_access_check_at", "review_score", "reviewed_by", "authority_override"),
    )

    if "slug" in update_data and update_data["slug"] != tool.slug:
        await check_unique(db, Tool, Tool.slug, update_data["slug"], exclude_id=tool_id, label="Slug")
    if "name" in update_data and update_data["name"] != tool.name:
        await check_unique(db, Tool, Tool.name, update_data["name"], exclude_id=tool_id, label="Tool name")

    old_status = ToolStatus(tool.status)

    if "status" in update_data:
        new_status = ToolStatus(update_data["status"])
        if new_status != old_status:
            valid = VALID_STATUS_TRANSITIONS.get(old_status, set())
            if new_status not in valid:
                # 409 而不是 400:请求本身没问题,是当前资源状态不允许这个操作
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Invalid status transition: {old_status} → {new_status}."
                        f" Valid targets: {sorted(valid) or 'none'}"
                    ),
                )
        # 首次转 published 才写日期,之后重发/改状态都不动它:
        # 它记的是"收录进本站的日期"(业务事实),不是"最近一次发布"。
        # 条件只看 published_at 空不空,顺带把"已 published 但没日期"的脏行补上,
        # 否则导出里就会出现一条没有 publishedAt 的已发布工具。
        if new_status == ToolStatus.PUBLISHED and not tool.published_at:
            # 日期取【库的会话时钟】而不是 date.today()(进程时钟): schema.sql 声明
            # 时间来源就是服务器会话时区, updated_at 也由库生成 —— 两个时钟不一致时
            # (容器 UTC + 库 +08), 同一次发布写出的 publishedAt 与 lastUpdatedAt 会差一天。
            tool.published_at = await db.scalar(select(func.current_date()))

    for key, value in update_data.items():
        if key not in ("topic_ids", "primary_topic_id", "review_score", "reviewed_by", "authority_override"):
            setattr(tool, key, value)

    # 人工复核:review_score 是唯一的结论字段,reviewed_at/by 由它驱动,不允许单独漂移。
    #   - 显式 null            → 撤销复核,三列一起清空
    #   - 有值                 → 复核时间取【库的会话时钟】(与 published_at 同一口径)
    #   - 只传 reviewed_by     → 只在已有复核结论时更新署名,不凭空造出"已复核"
    # 这几个字段【不能】进通用 setattr:否则 null 清 review_score 时 reviewed_at 会留旧值。
    review_score_sent = "review_score" in update_data
    reviewed_by_sent = "reviewed_by" in update_data
    if review_score_sent:
        tool.review_score = update_data["review_score"]
        if tool.review_score is None:
            tool.reviewed_at = None
            tool.reviewed_by = None
        else:
            tool.reviewed_at = await db.scalar(select(func.current_timestamp()))
            if reviewed_by_sent:
                tool.reviewed_by = update_data["reviewed_by"]
    elif reviewed_by_sent and tool.review_score is not None:
        tool.reviewed_by = update_data["reviewed_by"]

    # 人工覆盖权威度:改完立刻用 breakdown 里的 quality 快照重算分数,不调模型。
    # 这是"人改权重马上能看到排名变化"的关键 —— 否则每次调权重都要等一轮批处理。
    # 没有 breakdown(还没评过)时跳过:ai_score 仍是 0,下一轮评分会给出正确结果。
    if "authority_override" in update_data:
        tool.authority_override = update_data["authority_override"]
        effective = tool.authority_override if tool.authority_override is not None else tool.ai_authority
        if (
            recomputed := recompute_score(
                tool.ai_score_breakdown,
                effective,
                default_authority_weight=get_settings().scoring_authority_weight,
            )
        ) is not None:
            tool.ai_score = recomputed
            # breakdown 里的 effective 必须跟着改,否则快照会与 ai_score 自相矛盾。
            # 整份重新赋值(而不是原地改)是为了让 SQLAlchemy 的 JSON 列检测到变更。
            snapshot = dict(tool.ai_score_breakdown or {})
            authority = dict(snapshot.get("authority") or {})
            authority["effective"] = effective
            snapshot["authority"] = authority
            tool.ai_score_breakdown = snapshot

    if "topic_ids" in update_data or "primary_topic_id" in update_data:
        new_primary = update_data.get("primary_topic_id")
        if "topic_ids" in update_data:
            new_ids = list(update_data["topic_ids"])
            # ToolUpdate 没有 ToolCreate 那样的模型级校验,这条得自己拦
            if new_primary is not None and new_primary not in set(new_ids):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="primary_topic_id must be in topic_ids",
                )
            await replace_tool_topics(db, tool_id, topic_ids=new_ids, primary_topic_id=new_primary)
        else:
            # 只换主主题:目标必须已经是该工具的主题,否则等于凭空造一条归属
            current_ids = await ordered_topic_ids(db, tool_id)
            if new_primary not in current_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"primary_topic_id {new_primary} is not a topic of this tool",
                )
            await replace_tool_topics(db, tool_id, topic_ids=current_ids, primary_topic_id=new_primary)

    await db.flush()
    return await _reload_tool(db, tool_id)


@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_write)])
async def delete_tool(tool_id: int, db: DbSession) -> None:
    # 先锁父行再读: 本函数上面那段注释承诺"加锁顺序统一是先父行、再子行", 这里必须
    # 真的做到。用 db.get() 是【一致性读、不加锁】, 两个并发 DELETE 会各自读到这一行,
    # 后者的 DELETE 匹配 0 行, SQLAlchemy 抛 StaleDataError -> 全局处理器回 500,
    # 而正确答案是 404(它已经被前一个请求删掉了)。
    await lock_tool_row(db, tool_id)
    tool = await db.get(Tool, tool_id)
    if not tool:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found")
    # xg_tool_topic / xg_tool_link 都是 ON DELETE CASCADE,关联行跟着走
    await db.delete(tool)
    # 显式 flush: 级联删除在请求内真正执行完, 半途出错就是一次干净的 rollback,
    # 不会出现"响应已返回、事务在收尾时才失败"的中间态
    await db.flush()
