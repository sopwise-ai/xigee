#!/usr/bin/env python3
"""XiGee Studio API CLI — AI 调用 studio 接口的命令行工具。

用法:
  python skills/tools/api.py tools [--status S] [--topic-id N] [--featured] [--search K] [--page N] [--page-size N] [--json]  列出工具
  python skills/tools/api.py tool <id>                      查看工具详情
  python skills/tools/api.py add-tool --name <name> --tagline <一句话> --pricing <p> --origin <o> --access <a> --languages zh,en
                                  [--slug <slug>] [--url <url>] [--topic-ids 1,2] [--primary-topic-id N]
                                  [--tags a,b] [--open-source] [--featured] [--description <desc>]
                                  [--status {draft,pending}]
  python skills/tools/api.py update-tool <id> [--status S] [--name <name>] [--tagline <t>] [--description <desc>]
                                  [--pricing <p>] [--origin <o>] [--access <a>] [--languages zh,en] [--tags a,b]
                                  [--topic-ids 1,2] [--primary-topic-id N] [--open-source | --no-open-source]
                                  [--featured | --no-featured] [--slug <slug>]
                                  [--review-score N | --clear-review] [--reviewed-by <name>]
                                  [--authority 0-9 | --clear-authority]
  python skills/tools/api.py delete-tool <id>
  python skills/tools/api.py topics [--status {active,disabled}] [--page N] [--page-size N] [--json]   列出主题
  python skills/tools/api.py topic <id>                 查看主题详情
  python skills/tools/api.py add-topic --name <name> --slug <slug> [--icon <icon>] [--description <desc>] [--sort-order N] [--status {active,disabled}]
  python skills/tools/api.py update-topic <id> [--name <name>] [--slug <slug>] [--icon] [--description] [--sort-order N] [--status {active,disabled}]
  python skills/tools/api.py delete-topic <id>
  python skills/tools/api.py topic-count <id>           主题下已发布工具数
  python skills/tools/api.py topic-tools <id> [--page N] [--page-size N] [--json]   主题下全部工具
  python skills/tools/api.py tool-links <id> [--status {active,broken,disabled}]   列出工具链接
  python skills/tools/api.py add-link <tool_id> --url <url> [--label L] [--primary] [--status S] [--sort-order N]
  python skills/tools/api.py update-link <tool_id> <link_id> [--url <url>] [--label L] [--primary | --no-primary] [--status S] [--sort-order N]
  python skills/tools/api.py delete-link <tool_id> <link_id>
  python skills/tools/api.py tags [--json]              列出全部工具的标签（客户端聚合，无对应后端端点）
  python skills/tools/api.py tool-tags <id>             查看工具标签
  python skills/tools/api.py set-tags <tool_id> --tags a,b,c   全量替换工具标签
  python skills/tools/api.py tool-topics <id>           查看工具主题归属
  python skills/tools/api.py set-topics <tool_id> --topic-ids 1,2 [--primary-topic-id N]   全量替换主题归属
  python skills/tools/api.py export                     导出 JSON（两个文件: topics-{env}.json / tools-{env}.json）
  python skills/tools/api.py stats                      目录总览统计
  python skills/tools/api.py health                     健康检查
  python skills/tools/api.py env                        环境信息
  python skills/tools/api.py --version                  显示版本

状态取值（字符串，不再是 0/1/2/3）:
  tool:  draft | pending | published | archived   （合法迁移: draft→pending, pending→draft/published,
                                                     published→archived, archived→published；非法迁移返回 409）
  topic: disabled | active
  link:  active | broken | disabled

标签（tags）是工具自身字段（字符串数组，最多 8 个），随工具一起读写，没有独立端点。
所有写操作支持 --dry-run 预览、--op-id 幂等、操作日志。
注意: 只有读请求 (GET) 会自动退避重试；写操作 (POST/PUT/DELETE) 不重试，避免重复写入。
"""

__version__ = "2.1.0"

import argparse
import json
import logging
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

STUDIO_URL = os.environ.get("STUDIO_URL", "http://localhost:8000")

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_STUDIO_DIR = os.path.join(_PROJECT_ROOT, "studio")

_GLOBAL_ARGS: argparse.Namespace | None = None
_resolved_key: str | None = None
_backend_env: str | None = None

_TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(_TOOL_DIR, "api.log")
OP_IDS_FILE = os.path.join(_TOOL_DIR, ".op_ids")

_MAX_RETRIES = 3
_RETRY_DELAYS = [1, 2, 4]
_OP_IDS_MAX = 500
_MAX_FETCH_PAGES = 50

# 三张表的 status 是三套互不相干的枚举，别跨表复用。
TOOL_STATUS_NAMES = {
    "draft": "草稿",
    "pending": "待审核",
    "published": "已发布",
    "archived": "已下架",
}
TOPIC_STATUS_NAMES = {"disabled": "已禁用", "active": "启用"}
LINK_STATUS_NAMES = {"active": "可用", "broken": "失效", "disabled": "已禁用"}

LINK_LABELS = (
    "website",
    "api",
    "docs",
    "github",
    "playground",
    "pricing",
    "plugin",
    "other",
)


def _slugify(text: str) -> str:
    import re
    import unicodedata

    text = unicodedata.normalize("NFKC", text).strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    if text and re.match(r"^[a-z0-9-]+$", text):
        return text
    return re.sub(r"[^a-z0-9-]", "", text) or f"item-{secrets.token_hex(4)}"


logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("api")


def _load_op_ids() -> set[str]:
    if not os.path.exists(OP_IDS_FILE):
        return set()
    with open(OP_IDS_FILE) as f:
        return {line.strip() for line in f if line.strip()}


def _load_op_ids_ordered() -> list[str]:
    if not os.path.exists(OP_IDS_FILE):
        return []
    with open(OP_IDS_FILE) as f:
        seen = set()
        result = []
        for line in f:
            v = line.strip()
            if v and v not in seen:
                seen.add(v)
                result.append(v)
        return result


def _save_op_id(op_id: str):
    existing = _load_op_ids_ordered()
    if op_id in existing:
        return
    existing.append(op_id)
    if len(existing) > _OP_IDS_MAX:
        existing = existing[-_OP_IDS_MAX:]
    with open(OP_IDS_FILE, "w") as f:
        f.write("\n".join(existing) + "\n")


class CancelledError(SystemExit):
    def __init__(self):
        super().__init__(130)


def _confirm(prompt: str) -> bool:
    resp = input(f"  ⚠ {prompt} [y/N] ").strip().lower()
    return resp in ("y", "yes")


def _split_csv(raw: str) -> list[str]:
    """逗号分隔字符串 → 去空白后的非空列表。"""
    return [item.strip() for item in raw.split(",") if item.strip()]


def _split_int_csv(raw: str, flag: str) -> list[int]:
    """逗号分隔字符串 → int 列表；格式错误时报错退出。"""
    try:
        return [int(item) for item in _split_csv(raw)]
    except ValueError:
        print(
            f"错误: {flag} 格式无效，需逗号分隔的数字 (如 1,2,3)",
            file=sys.stderr,
        )
        sys.exit(1)


def _load_api_key_from_envfile(app_env: str) -> str:
    """从 studio/.env.{app_env} 读取 API_KEY 行。"""
    env_file = os.path.join(_STUDIO_DIR, f".env.{app_env}")
    if not os.path.exists(env_file):
        return ""
    try:
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("API_KEY="):
                    return line[len("API_KEY=") :].strip().strip("'\"")
    except OSError:
        pass
    return ""


def _detect_backend_env() -> str:
    """调用后端公开端点 /api/v1/env 获取当前后端环境 (dev/sit/prod)。

    CLI 据此后端环境读取对应的 studio/.env.{env}，确保与后端不脱节。
    结果缓存到 _backend_env，供生产环境保护逻辑使用。
    """
    global _backend_env
    if _backend_env is not None:
        return _backend_env
    url = f"{STUDIO_URL}/api/v1/env"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            _backend_env = data.get("env", "")
            return _backend_env
    except (urllib.error.URLError, ValueError, OSError):
        _backend_env = ""
        return ""


def _resolve_api_key() -> str:
    """解析 API Key。优先级: API_KEY > STUDIO_API_KEY > 自动探测后端环境读取 .env.{env}。"""
    global _resolved_key
    if _resolved_key:
        return _resolved_key
    key = os.environ.get("API_KEY") or os.environ.get("STUDIO_API_KEY", "")
    src = "环境变量"
    if not key:
        app_env = _detect_backend_env()
        if app_env:
            key = _load_api_key_from_envfile(app_env)
            src = f"studio/.env.{app_env}"
    if key:
        _resolved_key = key
        logger.info("API Key 来源: %s", src)
    return key


def _request(
    method: str, path: str, data: dict | None = None, need_auth: bool = False
) -> dict | list:
    result, _ = _request_with_headers(method, path, data, need_auth=need_auth)
    return result


def _request_with_headers(
    method: str, path: str, data: dict | None = None, need_auth: bool = False
) -> tuple[dict | list, dict]:
    url = f"{STUDIO_URL}/api/v1{path}"
    headers = {"Content-Type": "application/json"}
    if need_auth:
        api_key = _resolve_api_key()
        if not api_key:
            print("错误: 无法获取 API Key", file=sys.stderr)
            print(
                "  已尝试: 环境变量 API_KEY/STUDIO_API_KEY、自动探测后端 /api/v1/env 读取 .env.{env}",
                file=sys.stderr,
            )
            print("  请设置: export STUDIO_API_KEY=你的密钥", file=sys.stderr)
            print("  或确认 studio 已启动 (以便自动探测后端环境)", file=sys.stderr)
            sys.exit(2)
        headers["X-API-Key"] = api_key
    body = json.dumps(data).encode("utf-8") if data else None

    is_write = method in ("POST", "PUT", "DELETE")
    can_retry = not is_write

    for attempt in range(1, _MAX_RETRIES + 1):
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                resp_headers = {k.lower(): v for k, v in resp.headers.items()}
                if resp.status == 204:
                    return {}, resp_headers
                return json.loads(resp.read().decode("utf-8")), resp_headers
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            if 500 <= e.code < 600 and can_retry:
                if attempt < _MAX_RETRIES:
                    delay = _RETRY_DELAYS[attempt - 1]
                    logger.warning(
                        "重试 %d/%d: %s %s (等待 %ds)",
                        attempt,
                        _MAX_RETRIES,
                        method,
                        path,
                        delay,
                    )
                    time.sleep(delay)
                    continue
            else:
                logger.error(
                    "请求失败: %s %s → %d %s", method, path, e.code, error_body
                )
                print(f"HTTP {e.code}: {error_body}", file=sys.stderr)
                sys.exit(1)
        except urllib.error.URLError as e:
            if can_retry and attempt < _MAX_RETRIES:
                delay = _RETRY_DELAYS[attempt - 1]
                logger.warning(
                    "重试 %d/%d: %s %s (等待 %ds)",
                    attempt,
                    _MAX_RETRIES,
                    method,
                    path,
                    delay,
                )
                time.sleep(delay)
                continue
            err_msg = f"连接失败: {e.reason}"
            logger.error("连接失败: %s %s → %s", method, path, err_msg)
            print(err_msg, file=sys.stderr)
            print(f"请确认 studio 已启动 (STUDIO_URL={STUDIO_URL})", file=sys.stderr)
            sys.exit(1)

    logger.error("重试耗尽: %s %s", method, path)
    print("重试耗尽", file=sys.stderr)
    sys.exit(1)


def _write(
    method: str,
    path: str,
    payload: dict,
    *,
    need_auth: bool = True,
    summary: str = "",
    confirm: str = "",
) -> tuple[bool, dict | list]:
    assert _GLOBAL_ARGS is not None
    args = _GLOBAL_ARGS
    op_id = args.op_id or secrets.token_hex(8)

    if args.dry_run:
        print(f"  [DRY-RUN] {method} /api/v1{path}")
        print(f"  [DRY-RUN] 参数: {json.dumps(payload, ensure_ascii=False)}")
        logger.info(
            "DRY-RUN op_id=%s %s %s %s",
            op_id,
            method,
            path,
            json.dumps(payload, ensure_ascii=False),
        )
        return False, {}

    _parsed = urllib.parse.urlparse(STUDIO_URL)
    _target_local = _parsed.hostname in ("localhost", "127.0.0.1", "0.0.0.0")
    backend_env = ""
    if not _target_local:
        backend_env = _detect_backend_env()
    if backend_env == "prod":
        print("  ⚠⚠⚠ 当前为生产环境 (prod) ⚠⚠⚠", file=sys.stderr)
        print(f"  操作: {method} /api/v1{path}", file=sys.stderr)
        if not args.yes:
            print("  生产环境保护: 写操作必须显式 --yes 确认", file=sys.stderr)
            sys.exit(3)
        if method == "DELETE" and not getattr(args, "prod_confirm", False):
            print("  生产环境保护: DELETE 必须加 --prod-confirm 标志", file=sys.stderr)
            sys.exit(3)
        logger.warning("PROD 写操作 op_id=%s %s %s", op_id, method, path)

    completed = _load_op_ids()
    if op_id in completed:
        logger.info("跳过(已执行) op_id=%s %s %s", op_id, method, path)
        print(f"  - 操作已执行过 (op_id={op_id})，跳过")
        return False, {}

    if confirm and not args.yes:
        print(f"  操作: {summary}")
        if not _confirm(confirm):
            print("  已取消")
            logger.info("取消 op_id=%s %s %s", op_id, method, path)
            raise CancelledError()

    result = _request(method, path, payload, need_auth=need_auth)
    _save_op_id(op_id)
    logger.info(
        "SUCCESS op_id=%s %s %s → %s",
        op_id,
        method,
        path,
        json.dumps(result, ensure_ascii=False, default=str),
    )
    return True, result


def _print_json(data):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _display_width(s: str) -> int:
    return sum(2 if ord(c) > 127 else 1 for c in s)


def _pad_to_width(s: str, width: int) -> str:
    pad = width - _display_width(s)
    return s + " " * max(0, pad)


def _print_table(items: list, columns: list[str], headers: dict | None = None):
    if not items:
        print("  (空)")
        return
    display_headers = headers or {c: c for c in columns}
    widths = {
        c: max(
            _display_width(display_headers[c]),
            max(_display_width(str(item.get(c, ""))) for item in items),
        )
        for c in columns
    }
    header = "  ".join(_pad_to_width(display_headers[c], widths[c]) for c in columns)
    print(header)
    print("-" * _display_width(header))
    for item in items:
        row = "  ".join(_pad_to_width(str(item.get(c, "")), widths[c]) for c in columns)
        print(row)


def _print_total_info(resp_headers: dict):
    total = resp_headers.get("x-total-count")
    if total:
        print(f"  (共 {total} 条)")


def _csv_of(items: list, key: str) -> str:
    return ",".join(str(item.get(key, "")) for item in items)


# ── 工具 ──────────────────────────────────────────────────────────────────────


def cmd_tools(args):
    params = []
    if args.status is not None:
        params.append(f"status={args.status}")
    if args.topic_id is not None:
        params.append(f"topic_id={args.topic_id}")
    if args.featured:
        params.append("featured=true")
    if not args.search:
        # 无关键字时才把分页交给服务端。
        if args.page:
            params.append(f"page={args.page}")
        if args.page_size:
            params.append(f"page_size={args.page_size}")
    qs = "&".join(params)
    if args.search:
        # 后端 /tools 没有 search 参数: 服务端过滤(status/topic-id/featured) → 关键字过滤
        # (覆盖全部候选) → 客户端分页。分页不能交给服务端, 否则搜索只看得到第一页。
        keyword = args.search.lower()
        data = [
            t
            for t in _fetch_all(f"/tools?{qs}" if qs else "/tools")
            if keyword in (t.get("name") or "").lower()
            or keyword in (t.get("slug") or "").lower()
            or keyword in (t.get("tagline") or "").lower()
            or any(keyword in tag.lower() for tag in (t.get("tags") or []))
        ]
        total = len(data)
        page = args.page or 1
        page_size = args.page_size or 20
        data = (
            data[(max(page, 1) - 1) * page_size :][:page_size] if page_size > 0 else []
        )
        # CLI 不打印响应头, 表格尾部的 "(共 N 条)" 按关键字过滤后的总数显示。
        resp_headers = {"x-total-count": str(total)}
    else:
        data, resp_headers = _request_with_headers(
            "GET", f"/tools?{qs}" if qs else "/tools"
        )
    if args.json:
        _print_json(data)
    else:
        for t in data:
            t["status_name"] = TOOL_STATUS_NAMES.get(t.get("status"), "?")
            t["topic_names"] = _csv_of(t.get("topics") or [], "name")
            # 0 是合法权威度,不能用 or 兜底
            override = t.get("authority_override")
            t["authority"] = override if override is not None else t.get("ai_authority")
        _print_table(
            data,
            [
                "id",
                "name",
                "slug",
                "status_name",
                "ai_score",
                "authority",
                "pricing",
                "is_featured",
                "topic_names",
            ],
            headers={
                "id": "ID",
                "name": "名称",
                "slug": "Slug",
                "status_name": "状态",
                "ai_score": "AI分",
                "authority": "权威度",
                "pricing": "定价",
                "is_featured": "精选",
                "topic_names": "主题",
            },
        )
        _print_total_info(resp_headers)


def cmd_tool(args):
    data = _request("GET", f"/tools/{args.id}")
    _print_json(data)


def cmd_add_tool(args):
    payload = {
        "slug": args.slug if args.slug else _slugify(args.name),
        "name": args.name,
        "tagline": args.tagline,
        "pricing": args.pricing,
        "origin": args.origin,
        "access": args.access,
        "languages": _split_csv(args.languages),
        "status": args.status,
    }
    if args.open_source:
        payload["is_open_source"] = True
    if args.featured:
        payload["is_featured"] = True
    if args.url:
        payload["links"] = [{"url": args.url, "is_primary": True}]
    if args.topic_ids:
        payload["topic_ids"] = [
            int(c.strip()) for c in args.topic_ids.split(",") if c.strip()
        ]
    if args.primary_topic_id is not None:
        payload["primary_topic_id"] = args.primary_topic_id
    if args.tags:
        payload["tags"] = _split_csv(args.tags)
    if args.description is not None:
        payload["description"] = args.description
    _, data = _write("POST", "/tools", payload, summary=f"添加工具: {args.name}")
    if data:
        _print_json(data)


def cmd_update_tool(args):
    payload = {}
    if args.status is not None:
        payload["status"] = args.status
    if args.name:
        payload["name"] = args.name
    if args.tagline is not None:
        payload["tagline"] = args.tagline
    if args.description is not None:
        payload["description"] = args.description
    if args.pricing:
        payload["pricing"] = args.pricing
    if args.origin:
        payload["origin"] = args.origin
    if args.access:
        payload["access"] = args.access
    if args.languages is not None:
        payload["languages"] = _split_csv(args.languages)
    if args.tags is not None:
        payload["tags"] = _split_csv(args.tags)
    if args.topic_ids is not None:
        payload["topic_ids"] = _split_int_csv(args.topic_ids, "--topic-ids")
    if args.primary_topic_id is not None:
        payload["primary_topic_id"] = args.primary_topic_id
    if args.open_source is not None:
        payload["is_open_source"] = args.open_source
    if args.featured is not None:
        payload["is_featured"] = args.featured
    if args.slug:
        payload["slug"] = args.slug
    if args.clear_review:
        # 显式 null 才是"撤销复核"的语义；省略该键表示不动
        payload["review_score"] = None
    elif args.review_score is not None:
        payload["review_score"] = args.review_score
    if args.reviewed_by is not None:
        payload["reviewed_by"] = args.reviewed_by
    if args.clear_authority:
        # null = 撤销人工覆盖,回到 AI 判断的权威度(并即时重算分数)
        payload["authority_override"] = None
    elif args.authority is not None:
        payload["authority_override"] = args.authority

    confirm_text = ""
    new_status_name = TOOL_STATUS_NAMES.get(args.status or "", "?")
    if args.status is not None and not (_GLOBAL_ARGS and _GLOBAL_ARGS.dry_run):
        # dry-run 不该碰网络：只在真正要写时才回读旧状态做确认文案。
        old = _request("GET", f"/tools/{args.id}")
        old_status_name = TOOL_STATUS_NAMES.get(old.get("status"), "?")
        summary = f"更新工具 {args.id}: 状态 {old_status_name}→{new_status_name}"
        confirm_text = (
            f"将工具 {args.id} 从「{old_status_name}」改为「{new_status_name}」?"
        )
    elif args.status is not None:
        summary = f"更新工具 {args.id}: 状态 →{new_status_name}"
    else:
        keys = ", ".join(payload.keys())
        summary = f"更新工具 {args.id}: {keys}"

    _, data = _write(
        "PUT", f"/tools/{args.id}", payload, summary=summary, confirm=confirm_text
    )
    if data:
        _print_json(data)


def cmd_delete_tool(args):
    name = f"ID={args.id}"
    if not (_GLOBAL_ARGS and _GLOBAL_ARGS.dry_run):
        name = _request("GET", f"/tools/{args.id}").get("name", name)
    summary = f"删除工具: {name}"
    executed, _ = _write(
        "DELETE",
        f"/tools/{args.id}",
        {},
        summary=summary,
        confirm=f"确认删除工具「{name}」? 此操作不可恢复!",
    )
    if executed:
        print(f"工具 {args.id} 已删除")


# ── 主题 ──────────────────────────────────────────────────────────────────────


def cmd_topics(args):
    params = []
    if args.status is not None:
        params.append(f"status={args.status}")
    if args.page:
        params.append(f"page={args.page}")
    if args.page_size:
        params.append(f"page_size={args.page_size}")
    qs = "&".join(params)
    data, resp_headers = _request_with_headers(
        "GET", f"/topics?{qs}" if qs else "/topics"
    )
    if args.json:
        _print_json(data)
    else:
        for t in data:
            t["status_name"] = TOPIC_STATUS_NAMES.get(t.get("status"), "?")
        _print_table(
            data,
            ["id", "name", "slug", "icon", "sort_order", "status_name", "tool_count"],
            headers={
                "id": "ID",
                "name": "名称",
                "slug": "Slug",
                "icon": "图标",
                "sort_order": "排序",
                "status_name": "状态",
                "tool_count": "已发布工具数",
            },
        )
        _print_total_info(resp_headers)


def cmd_topic(args):
    data = _request("GET", f"/topics/{args.id}")
    _print_json(data)


def cmd_add_topic(args):
    payload = {"slug": args.slug, "name": args.name}
    if args.icon is not None:
        payload["icon"] = args.icon
    if args.description is not None:
        payload["description"] = args.description
    if args.sort_order is not None:
        payload["sort_order"] = args.sort_order
    if args.status is not None:
        payload["status"] = args.status
    _, data = _write("POST", "/topics", payload, summary=f"添加主题: {args.name}")
    if data:
        _print_json(data)


def cmd_update_topic(args):
    payload = {}
    if args.name is not None:
        payload["name"] = args.name
    if args.slug is not None:
        payload["slug"] = args.slug
    if args.icon is not None:
        payload["icon"] = args.icon
    if args.description is not None:
        payload["description"] = args.description
    if args.sort_order is not None:
        payload["sort_order"] = args.sort_order
    if args.status is not None:
        payload["status"] = args.status
    _, data = _write(
        "PUT", f"/topics/{args.id}", payload, summary=f"更新主题: {args.id}"
    )
    if data:
        _print_json(data)


def cmd_delete_topic(args):
    name = f"ID={args.id}"
    if not (_GLOBAL_ARGS and _GLOBAL_ARGS.dry_run):
        name = _request("GET", f"/topics/{args.id}").get("name", name)
    executed, _ = _write(
        "DELETE",
        f"/topics/{args.id}",
        {},
        summary=f"删除主题: {name}",
        confirm=f"确认删除主题「{name}」? 此操作不可恢复!",
    )
    if executed:
        print(f"主题 {args.id} 已删除")


def cmd_topic_count(args):
    data = _request("GET", f"/topics/{args.id}/tool-count")
    print(f"已发布工具数: {data.get('tool_count', 0)}")


def cmd_topic_tools(args):
    params = []
    if args.page:
        params.append(f"page={args.page}")
    if args.page_size:
        params.append(f"page_size={args.page_size}")
    qs = "&".join(params)
    data, resp_headers = _request_with_headers(
        "GET",
        f"/topics/{args.id}/tools?{qs}" if qs else f"/topics/{args.id}/tools",
    )
    if args.json:
        _print_json(data)
    else:
        for t in data:
            t["status_name"] = TOOL_STATUS_NAMES.get(t.get("status"), "?")
        _print_table(
            data,
            ["id", "name", "slug", "status_name", "pricing"],
            headers={
                "id": "ID",
                "name": "名称",
                "slug": "Slug",
                "status_name": "状态",
                "pricing": "定价",
            },
        )
        _print_total_info(resp_headers)


# ── 链接 ──────────────────────────────────────────────────────────────────────


def cmd_tool_links(args):
    params = []
    if args.status is not None:
        params.append(f"status={args.status}")
    qs = "&".join(params)
    data = _request(
        "GET", f"/tools/{args.id}/links?{qs}" if qs else f"/tools/{args.id}/links"
    )
    for link in data:
        link["status_name"] = LINK_STATUS_NAMES.get(link.get("status"), "?")
    _print_table(
        data,
        ["id", "url", "label", "is_primary", "status_name"],
        headers={
            "id": "ID",
            "url": "URL",
            "label": "类型",
            "is_primary": "主链接",
            "status_name": "状态",
        },
    )


def cmd_add_link(args):
    payload = {"url": args.url}
    if args.label:
        payload["label"] = args.label
    if args.primary:
        payload["is_primary"] = True
    if args.status is not None:
        payload["status"] = args.status
    if args.sort_order is not None:
        payload["sort_order"] = args.sort_order
    _, data = _write(
        "POST",
        f"/tools/{args.tool_id}/links",
        payload,
        summary=f"添加链接: {args.url}",
    )
    if data:
        _print_json(data)


def cmd_update_link(args):
    payload = {}
    if args.url is not None:
        payload["url"] = args.url
    if args.label is not None:
        payload["label"] = args.label
    if args.primary is not None:
        payload["is_primary"] = args.primary
    if args.status is not None:
        payload["status"] = args.status
    if args.sort_order is not None:
        payload["sort_order"] = args.sort_order
    _, data = _write(
        "PUT",
        f"/tools/{args.tool_id}/links/{args.link_id}",
        payload,
        summary=f"更新链接: {args.link_id}",
    )
    if data:
        _print_json(data)


def cmd_delete_link(args):
    executed, _ = _write(
        "DELETE",
        f"/tools/{args.tool_id}/links/{args.link_id}",
        {},
        summary=f"删除链接: {args.link_id}",
        confirm=f"确认删除链接 {args.link_id}?",
    )
    if executed:
        print(f"链接 {args.link_id} 已删除")


# ── 标签（工具字段，无独立端点） ───────────────────────────────────────────────


def cmd_tags(args):
    """列出全部工具的标签（客户端聚合）。

    新模型里标签只是 xg_tool.tags JSON 列，没有 /tags 端点，所以这里拉全量工具
    后自行去重计数。
    """
    counts: dict[str, int] = {}
    for tool in _fetch_all("/tools"):
        for tag in tool.get("tags") or []:
            counts[tag] = counts.get(tag, 0) + 1
    items = [
        {"tag": tag, "tool_count": count}
        for tag, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    if args.json:
        _print_json(items)
    else:
        _print_table(
            items,
            ["tag", "tool_count"],
            headers={"tag": "标签", "tool_count": "工具数"},
        )


def cmd_tool_tags(args):
    data = _request("GET", f"/tools/{args.id}")
    tags = data.get("tags") or []
    _print_table(
        [{"tag": tag} for tag in tags],
        ["tag"],
        headers={"tag": "标签"},
    )


def cmd_set_tags(args):
    tags = _split_csv(args.tags)
    payload = {"tags": tags}
    _, data = _write(
        "PUT",
        f"/tools/{args.tool_id}",
        payload,
        summary=f"设置标签: {args.tool_id} → {tags}",
        confirm=f"将工具 {args.tool_id} 的标签全量替换为 {tags}?",
    )
    if data:
        _print_json(data)


def cmd_tool_topics(args):
    data = _request("GET", f"/tools/{args.id}")
    topics = data.get("topics") or []
    primary_topic_id = data.get("primary_topic_id")
    for topic in topics:
        topic["is_primary"] = topic.get("id") == primary_topic_id
    _print_table(
        topics,
        ["id", "name", "slug", "is_primary"],
        headers={
            "id": "ID",
            "name": "名称",
            "slug": "Slug",
            "is_primary": "主主题",
        },
    )


def cmd_set_topics(args):
    topic_ids = _split_int_csv(args.topic_ids, "--topic-ids")
    if not topic_ids:
        print("错误: --topic-ids 不能为空", file=sys.stderr)
        sys.exit(1)
    payload = {"topic_ids": topic_ids}
    if args.primary_topic_id is not None:
        payload["primary_topic_id"] = args.primary_topic_id
    _, data = _write(
        "PUT",
        f"/tools/{args.tool_id}/topics",
        payload,
        summary=f"设置主题归属: {args.tool_id} → {topic_ids}",
        confirm=f"将工具 {args.tool_id} 的主题归属全量替换为 {topic_ids}?",
    )
    if data:
        _print_json(data)


# ── 系统 ──────────────────────────────────────────────────────────────────────


def cmd_export(args):
    data = _request("POST", "/export", need_auth=True)
    _print_json(data)


def _fetch_all(path: str, page_size: int = 100) -> list:
    results = []
    page = 1
    while page <= _MAX_FETCH_PAGES:
        sep = "&" if "?" in path else "?"
        data, _ = _request_with_headers(
            "GET", f"{path}{sep}page={page}&page_size={page_size}"
        )
        results.extend(data)
        if len(data) < page_size:
            break
        page += 1
    return results


def cmd_stats(args):
    all_tools = _fetch_all("/tools")
    topics = _fetch_all("/topics", page_size=200)

    status_counts = dict.fromkeys(TOOL_STATUS_NAMES, 0)
    for t in all_tools:
        s = t.get("status", "draft")
        status_counts[s] = status_counts.get(s, 0) + 1

    # 标签是工具字段，没有 /tags 端点：总数在客户端去重统计。
    distinct_tags = {tag for t in all_tools for tag in (t.get("tags") or [])}

    print("═══ XiGee 统计 ═══")
    print(f"  主题总数: {len(topics)}")
    print(f"  标签总数(去重): {len(distinct_tags)}")
    print(f"  工具总数: {len(all_tools)}")
    print()
    print("  工具状态分布:")
    for s, name in TOOL_STATUS_NAMES.items():
        print(f"    {name} (status={s}): {status_counts.get(s, 0)}")


def cmd_health(args):
    data = _request("GET", "/health")
    backend_env = _detect_backend_env()
    data["env"] = backend_env
    _print_json(data)
    if backend_env == "prod":
        print("  ⚠⚠⚠ 生产环境 (prod): 写操作需 --yes, DELETE 需 --prod-confirm ⚠⚠⚠")


def cmd_env(args):
    data = _request("GET", "/env")
    _print_json(data)


def main():
    parser = argparse.ArgumentParser(description="XiGee Studio API CLI")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际写入")
    parser.add_argument("--yes", action="store_true", help="跳过二次确认")
    parser.add_argument(
        "--prod-confirm",
        action="store_true",
        help="生产环境 DELETE 显式确认",
    )
    parser.add_argument("--op-id", help="幂等键，相同 op_id 的操作不会重复执行")
    sub = parser.add_subparsers(dest="command", required=True)

    tool_status = tuple(TOOL_STATUS_NAMES)
    topic_status = tuple(TOPIC_STATUS_NAMES)
    link_status = tuple(LINK_STATUS_NAMES)
    pricing = ("free", "freemium", "paid")
    origin = ("cn", "overseas")
    access = ("direct", "proxy")

    # tools
    p = sub.add_parser("tools", aliases=["t"], help="列出工具")
    p.add_argument("--status", choices=tool_status, help="按状态过滤")
    p.add_argument("--topic-id", type=int, help="按主题过滤")
    p.add_argument("--featured", action="store_true", help="仅精选")
    p.add_argument(
        "--search", help="按名称/slug/tagline/标签搜索（覆盖全部候选，结果客户端分页）"
    )
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--page-size", type=int, default=20)
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.set_defaults(func=cmd_tools)

    # tool detail
    p = sub.add_parser("tool", help="查看工具详情")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_tool)

    # add tool
    p = sub.add_parser("add-tool", help="添加工具")
    p.add_argument("--name", required=True)
    p.add_argument("--tagline", required=True, help="一句话简介，须以标点结尾")
    p.add_argument("--pricing", required=True, choices=pricing)
    p.add_argument("--origin", required=True, choices=origin)
    p.add_argument("--access", required=True, choices=access)
    p.add_argument("--languages", required=True, help="ISO 639-1 逗号分隔 (如 zh,en)")
    p.add_argument("--slug", help="默认从 name 生成")
    p.add_argument("--url", help="工具主链接")
    p.add_argument("--topic-ids", help="逗号分隔的主题 ID (如 1,2,3)")
    p.add_argument("--primary-topic-id", type=int, default=None)
    p.add_argument("--tags", help="逗号分隔的标签 (最多 8 个)")
    p.add_argument("--open-source", action="store_true", help="标记为开源")
    p.add_argument("--featured", action="store_true")
    p.add_argument("--description")
    p.add_argument(
        "--status",
        choices=("draft", "pending"),
        default="draft",
        help="新建只允许 draft/pending",
    )
    p.set_defaults(func=cmd_add_tool)

    # update tool
    p = sub.add_parser("update-tool", help="更新工具")
    p.add_argument("id", type=int)
    p.add_argument("--status", choices=tool_status)
    p.add_argument("--name")
    p.add_argument("--tagline")
    p.add_argument("--description")
    p.add_argument("--pricing", choices=pricing)
    p.add_argument("--origin", choices=origin)
    p.add_argument("--access", choices=access)
    p.add_argument("--languages", help="逗号分隔，全量替换")
    p.add_argument("--tags", help="逗号分隔，全量替换；传空串清空")
    p.add_argument("--topic-ids", help="逗号分隔的主题 ID，全量替换；传空串清空")
    p.add_argument("--primary-topic-id", type=int, default=None)
    p.add_argument("--open-source", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--featured", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--slug")
    p.add_argument(
        "--review-score",
        type=int,
        default=None,
        help="人工复核分 0~1000（写入后自动记复核时间；不参与排序）",
    )
    p.add_argument(
        "--clear-review", action="store_true", help="撤销复核（review_score 置 NULL）"
    )
    p.add_argument("--reviewed-by", default=None, help="复核人标识")
    p.add_argument(
        "--authority",
        type=int,
        default=None,
        metavar="0-9",
        help="人工覆盖行业权威度(0~9);会即时重算 ai_score,不调模型",
    )
    p.add_argument(
        "--clear-authority",
        action="store_true",
        help="撤销人工覆盖,回到 AI 判断的权威度",
    )
    p.set_defaults(func=cmd_update_tool)

    # delete tool
    p = sub.add_parser("delete-tool", help="删除工具")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_delete_tool)

    # topics
    p = sub.add_parser("topics", aliases=["tp"], help="列出主题")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--page-size", type=int, default=50)
    p.add_argument("--status", choices=topic_status, default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_topics)

    # topic detail
    p = sub.add_parser("topic", help="查看主题详情")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_topic)

    # add topic
    p = sub.add_parser("add-topic", help="添加主题")
    p.add_argument("--name", required=True)
    p.add_argument("--slug", required=True)
    p.add_argument("--icon", help="emoji 图标字符，默认 📦")
    p.add_argument("--description")
    p.add_argument("--sort-order", type=int, default=None)
    p.add_argument("--status", choices=topic_status, default=None)
    p.set_defaults(func=cmd_add_topic)

    # update topic
    p = sub.add_parser("update-topic", help="更新主题")
    p.add_argument("id", type=int)
    p.add_argument("--name")
    p.add_argument("--slug")
    p.add_argument("--icon")
    p.add_argument("--description")
    p.add_argument("--sort-order", type=int)
    p.add_argument("--status", choices=topic_status)
    p.set_defaults(func=cmd_update_topic)

    # delete topic
    p = sub.add_parser("delete-topic", help="删除主题")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_delete_topic)

    # topic count
    p = sub.add_parser("topic-count", help="主题下已发布工具数")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_topic_count)

    # topic tools
    p = sub.add_parser("topic-tools", help="主题下全部工具")
    p.add_argument("id", type=int)
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--page-size", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_topic_tools)

    # tool links
    p = sub.add_parser("tool-links", help="列出工具链接")
    p.add_argument("id", type=int)
    p.add_argument("--status", choices=link_status, default=None)
    p.set_defaults(func=cmd_tool_links)

    # add link
    p = sub.add_parser("add-link", help="添加工具链接")
    p.add_argument("tool_id", type=int)
    p.add_argument("--url", required=True)
    p.add_argument("--label", choices=LINK_LABELS)
    p.add_argument("--primary", action="store_true")
    p.add_argument("--status", choices=link_status, default=None)
    p.add_argument("--sort-order", type=int, default=None)
    p.set_defaults(func=cmd_add_link)

    # update link
    p = sub.add_parser("update-link", help="更新工具链接")
    p.add_argument("tool_id", type=int)
    p.add_argument("link_id", type=int)
    p.add_argument("--url")
    p.add_argument("--label", choices=LINK_LABELS)
    p.add_argument("--primary", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--status", choices=link_status, default=None)
    p.add_argument("--sort-order", type=int, default=None)
    p.set_defaults(func=cmd_update_link)

    # delete link
    p = sub.add_parser("delete-link", help="删除工具链接")
    p.add_argument("tool_id", type=int)
    p.add_argument("link_id", type=int)
    p.set_defaults(func=cmd_delete_link)

    # tags (aggregate)
    p = sub.add_parser("tags", help="列出全部工具的标签（客户端聚合）")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_tags)

    # tool tags
    p = sub.add_parser("tool-tags", help="查看工具标签")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_tool_tags)

    # set tags
    p = sub.add_parser("set-tags", help="全量替换工具标签")
    p.add_argument("tool_id", type=int)
    p.add_argument("--tags", required=True, help="逗号分隔的标签；传空串清空")
    p.set_defaults(func=cmd_set_tags)

    # tool topics
    p = sub.add_parser("tool-topics", help="查看工具主题归属")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_tool_topics)

    # set topics
    p = sub.add_parser("set-topics", help="全量替换工具主题归属")
    p.add_argument("tool_id", type=int)
    p.add_argument("--topic-ids", required=True, help="逗号分隔的主题 ID")
    p.add_argument("--primary-topic-id", type=int, default=None)
    p.set_defaults(func=cmd_set_topics)

    # export
    p = sub.add_parser("export", help="导出 JSON")
    p.set_defaults(func=cmd_export)

    # stats
    p = sub.add_parser("stats", help="目录统计")
    p.set_defaults(func=cmd_stats)

    # health
    p = sub.add_parser("health", help="健康检查")
    p.set_defaults(func=cmd_health)

    # env
    p = sub.add_parser("env", help="环境信息")
    p.set_defaults(func=cmd_env)

    global _GLOBAL_ARGS
    args = parser.parse_args()
    _GLOBAL_ARGS = args
    args.func(args)


if __name__ == "__main__":
    main()
