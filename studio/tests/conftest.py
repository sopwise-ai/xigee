"""公共 fixtures -- 所有测试共享。

设计原则:
  1. 每个测试函数独立, 不依赖其他测试的副作用
  2. clean_db 仅在 setup 阶段清理(下一个测试的 setup 会再清理一次, teardown 冗余)
  3. async_client fixture 提供带 API Key 的 httpx AsyncClient
  4. api_headers fixture 提供导出端点鉴权
  5. 工厂函数简化测试数据构造

表名已从上一代的 sd_product* 换到 xg_*: TRUNCATE 顺序按外键依赖从子到父,
外加 FOREIGN_KEY_CHECKS=0 兜底(否则父表 TRUNCATE 会被 RESTRICT 外键挡住)。

⚠ clean_db 是【破坏性】的: 它把整张 xg_* 表清空。默认连的又是一个名字带 sit 的
远端共享库, 所以进 TRUNCATE 之前必须过 _guard_destructive_db 那道门禁(见下)。
"""

import logging
import os
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text, update

from app.core.config import Settings, get_settings
from app.core.database import AsyncSessionLocal, engine
from app.main import app
from app.models import Tool, ToolStatus

settings = get_settings()
API_KEY = settings.api_key

# 抑制测试中的 SQL 日志
engine.echo = False
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

# 子表在前: 即便将来去掉 FOREIGN_KEY_CHECKS=0 也能按顺序清干净
_TABLES = [
    "xg_tool_link",
    "xg_tool_topic",
    "xg_tool",
    "xg_topic",
]

# ── 破坏性测试的库门禁 ────────────────────────────────────────────────────────
# clean_db 会清空整张表。默认的 dev 配置连的是 10.182.32.31:3312/mfbp_kazar_sit
# —— 库名里写着 sit, 并不保证"用完即弃"。清错了没有第二次机会, 所以这里放一道
# 硬门禁, 而不是靠"大家记得别连错"。
_TRUNCATE_OVERRIDE_ENV = "STUDIO_ALLOW_SHARED_DB_TRUNCATE"
_PROD_HINTS = ("prod", "prd", "production")
_guard_checked = False


def _unsafe_to_truncate(settings: Settings, *, allow_shared: bool) -> str | None:
    """返回拒绝理由(可以清库则 None)。拆成纯函数是为了能被单测直接覆盖判定矩阵。

    口径, 由严格到宽松:
      1. 【永远拒绝】app_env=prod, 或 db_name/db_host 命中 prod/prd/production。
         这一条不接受任何环境变量豁免。
      2. 【直接放行】db_name 含 test —— 专用测试库, 无需额外开关。
         刻意【不看】app_env: AppEnv 只有 dev/sit/prod 三个取值, 判 app_env == "test"
         是永远走不到的分支(Settings 会先把 APP_ENV=test 拒掉)。这里曾经有那条分支,
         而且还有一条绕过 Settings 校验的用例在替它背书 —— 想加 test 出口, 先看
         tests/test_db_safety.py 里钉住这个约束的那条用例。
      3. 【需显式开关】其余情况(例如 dev 指向名字带 sit 的共享库)必须设置
         STUDIO_ALLOW_SHARED_DB_TRUNCATE=1 才放行。
    """
    name = (settings.db_name or "").lower()
    host = (settings.db_host or "").lower()
    target = f"{host}/{name}"

    if settings.app_env == "prod" or any(hint in name or hint in host for hint in _PROD_HINTS):
        return f"目标库疑似生产环境({target}), 拒绝运行破坏性测试"
    if "test" in name:
        return None
    if allow_shared:
        return None
    return (
        f"clean_db 会 TRUNCATE {target} 上的 xg_* 表, 但它看起来不是专用测试库。"
        f" 确认无误后请设置 {_TRUNCATE_OVERRIDE_ENV}=1 再跑"
    )


def _guard_destructive_db(settings: Settings) -> None:
    """门禁在第一次 clean_db 之前跑一次; 不通过则整场退出(不会碰库)。"""
    allow_shared = os.getenv(_TRUNCATE_OVERRIDE_ENV) == "1"
    if reason := _unsafe_to_truncate(settings, allow_shared=allow_shared):
        pytest.exit(reason, returncode=3)
    if allow_shared and "test" not in (settings.db_name or "").lower():
        logging.getLogger(__name__).warning(
            "clean_db 将在共享库 %s/%s 上 TRUNCATE xg_* 表(由 %s=1 显式放行)",
            settings.db_host,
            settings.db_name,
            _TRUNCATE_OVERRIDE_ENV,
        )


@pytest_asyncio.fixture(autouse=True)
async def clean_db():
    """每个测试前自动清理所有 xg_* 表数据, 保证测试隔离。"""
    global _guard_checked
    if not _guard_checked:
        _guard_destructive_db(settings)
        _guard_checked = True

    async with AsyncSessionLocal() as session:
        await session.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for table in _TABLES:
            await session.execute(text(f"TRUNCATE TABLE {table}"))
        await session.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        await session.commit()


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": API_KEY},
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def anon_client() -> AsyncGenerator[AsyncClient]:
    """Client without API key -- for testing auth failures."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# ── 配置构造 ──────────────────────────────────────────────────────────────────


def isolated_settings(**overrides: Any) -> Settings:
    """构造一个与【外界无关】的 Settings: 不读 .env.<env>, 也不吃进程环境变量。

    两条隔离都必需, 少第二条会出真事: `_env_file=None` 只管文件, 而 CI 里
    DB_PORT=3307 是【进程环境变量】, 照样会被读进来 —— 于是"整串 database_url 相等"
    这类断言本地过、CI 挂(本仓库首次接入 CI 时就挂在这上面)。init 参数优先级最高,
    所以把每个字段按声明的默认值显式传一遍才真隔离; 用 model_fields 取默认值是为了
    将来加字段时不必回来补这份清单。

    db_name / db_user 的声明默认值是空串, 而校验器不允许空, 所以额外兜一组合法值。
    """
    declared = {name: field.get_default(call_default_factory=True) for name, field in Settings.model_fields.items()}
    return Settings(
        _env_file=None,
        **{
            **declared,
            "db_host": "localhost",
            "db_name": "testdb",
            "db_user": "tester",
            **overrides,
        },
    )


# ── 工厂函数 ──────────────────────────────────────────────────────────────────


async def create_topic(
    client: AsyncClient,
    slug: str = "test-topic",
    name: str = "测试主题",
    icon: str = "📦",
    description: str | None = None,
    sort_order: int = 0,
    status: str = "active",
) -> dict[str, Any]:
    payload: dict[str, Any] = {"slug": slug, "name": name, "icon": icon, "sort_order": sort_order, "status": status}
    if description is not None:
        payload["description"] = description
    resp = await client.post("/api/v1/topics", json=payload)
    assert resp.status_code == 201, resp.text
    # resp.json() 是 Any, 显式落到 dict 上: 工厂函数的返回值必须是有形状的,
    # 否则 mypy 的 warn_return_any 会一路往上传染(以前它是返回 Any 的)
    data: dict[str, Any] = resp.json()
    return data


async def create_tool(
    client: AsyncClient,
    slug: str = "test-tool",
    name: str = "测试工具",
    *,
    tagline: str = "测试工具的一句话简介。",
    description: str | None = None,
    pricing: str = "free",
    is_open_source: bool = False,
    origin: str = "overseas",
    access: str = "direct",
    languages: list[str] | None = None,
    tags: list[str] | None = None,
    is_featured: bool = False,
    ai_score: int = 0,
    status: str = ToolStatus.DRAFT,
    topic_ids: list[int] | None = None,
    primary_topic_id: int | None = None,
    links: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """建工具。

    status 传 published/archived 时自动补走迁移流程: create 只允许 draft/pending,
    所以先建成 pending, 再用 PUT 推到目标状态 -- 这也顺带验证了 published_at 的写入时机。
    """
    wanted = str(status)
    needs_publish = wanted in (ToolStatus.PUBLISHED, ToolStatus.ARCHIVED)
    create_status = ToolStatus.PENDING if needs_publish else wanted

    payload: dict[str, Any] = {
        "slug": slug,
        "name": name,
        "tagline": tagline,
        "pricing": pricing,
        "is_open_source": is_open_source,
        "origin": origin,
        "access": access,
        "languages": languages if languages is not None else ["zh"],
        "tags": tags if tags is not None else [],
        "is_featured": is_featured,
        "status": create_status,
    }
    if description is not None:
        payload["description"] = description
    if topic_ids:
        payload["topic_ids"] = topic_ids
    if primary_topic_id is not None:
        payload["primary_topic_id"] = primary_topic_id
    if links:
        payload["links"] = links

    resp = await client.post("/api/v1/tools", json=payload)
    assert resp.status_code == 201, resp.text
    data: dict[str, Any] = resp.json()

    if needs_publish:
        resp = await client.put(f"/api/v1/tools/{data['id']}", json={"status": ToolStatus.PUBLISHED})
        assert resp.status_code == 200, resp.text
        data = resp.json()

    if wanted == ToolStatus.ARCHIVED:
        resp = await client.put(f"/api/v1/tools/{data['id']}", json={"status": ToolStatus.ARCHIVED})
        assert resp.status_code == 200, resp.text
        data = resp.json()

    if ai_score:
        # ai_score 是派生列,API 刻意不提供写入口(唯一写入口是 app/scoring 管线)。
        # 测试里要造排序场景,就直接改库 —— 和管线写回的是同一列,语义一致。
        async with AsyncSessionLocal() as session:
            await session.execute(update(Tool).where(Tool.id == data["id"]).values(ai_score=ai_score))
            await session.commit()
        data["ai_score"] = ai_score

    return data


async def create_link(
    client: AsyncClient,
    tool_id: int,
    url: str = "https://example.com",
    label: str | None = None,
    is_primary: bool = False,
    status: str = "active",
    sort_order: int = 0,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"url": url, "is_primary": is_primary, "status": status, "sort_order": sort_order}
    if label:
        payload["label"] = label
    resp = await client.post(f"/api/v1/tools/{tool_id}/links", json=payload)
    assert resp.status_code == 201, resp.text
    # resp.json() 是 Any, 显式落到 dict 上: 工厂函数的返回值必须是有形状的,
    # 否则 mypy 的 warn_return_any 会一路往上传染(以前它是返回 Any 的)
    data: dict[str, Any] = resp.json()
    return data
