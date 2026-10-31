# XiGee Directory — AI Agent 规则

## 项目概述

AI 驱动的目录站 (XiGee), 包含三个模块:

- `web/` — Next.js 前端, 展示数据 (Vercel 部署)
- `studio/` — FastAPI 后端, 管理数据 (uv + Python 3.13)
- `skills/` — AI 套件, 驱动数据管理流程

## 数据流

```
数据库 ← studio (FastAPI CRUD)
         ↓
    studio 导出 JSON → web/data/topics-{env}.json + tools-{env}.json
                       prod 额外同步 topics.json + tools.json
         │
         └─ ✅ 前端读 web/data/topics.json + tools.json（data.json 已删除）
            (契约分叉与待办见 web/AGENTS.md 的「数据源」一节)
         ↑
    skills/tools/api.py 调用 studio API
    .opencode/commands/ 触发 AI 工作流
```

## 工具状态流程

```
draft=草稿 → pending=待审核 → published=已发布 → archived=已下架
```

- 仅 status=published 且存在 status=active 链接的工具进导出产物
- published_at 仅在首次 status→published 时写入
- 合法状态转换: draft→pending, pending→draft, pending→published, published→archived, archived→published
- 非法状态迁移后端返回 409 (不是 400)
- 主题 (topic) 状态: active / disabled; 链接 (link) 状态: active / broken / disabled

## 开发命令

```bash
# 启动服务
./scripts/dev.sh                # 前端 + 后端
./scripts/dev-web.sh            # 仅前端 (port 3000, 前端没有配置文件)
./scripts/dev-studio.sh         # 仅后端 (端口取 studio/.env.<APP_ENV> 的 APP_PORT, 缺省 8000)
./scripts/stop.sh               # 停止服务
./scripts/status.sh             # 查看状态

# 数据管理 (通过 skills/tools/api.py)
python skills/tools/api.py stats                        # 目录统计
python skills/tools/api.py tools --status pending       # 待审核工具
python skills/tools/api.py export                       # 导出 JSON

# 后端检查与测试
cd studio && make check                                 # ruff + mypy + 格式校验
cd studio && make test ALLOW_SHARED_DB=1                # 默认 dev 是共享库: 直接 uv run pytest 会被门禁以退出码 3 拦住
```

非 prod 环境没有 `--yes` 强制要求。交互式二次确认 (y/N) 的真实范围很窄: 只有**带 `--status` 的
`update-tool`**, 以及 `set-tags` / `set-topics` / `delete-tool` / `delete-topic` /
`delete-link` —— 在 agent 的非交互场景下这几条必须带 `--yes`, 否则 `input()` 抛 EOFError 退出 1。
`update-tool` **不带 `--status`** (改名/改 slug/改描述/改主题/改定价等) 没有任何确认, 直接落库退出 0;
`add-tool` / `add-topic` / `add-link` 同样无确认, 会直接写库。`export` 不走 `_write`, 因此
`--dry-run` / `--op-id` 会被忽略 (仍然写盘), 也不触发 prod 的 `--yes` 门槛。

## Studio API 端点

| 方法           | 路径                                    | 说明               | 需 X-API-Key  |
| -------------- | --------------------------------------- | ------------------ | ------------- |
| GET/POST       | /api/v1/topics                          | 主题 CRUD          | 仅 POST       |
| GET/PUT/DELETE | /api/v1/topics/{topic_id}               | 主题详情           | 仅 PUT/DELETE |
| GET            | /api/v1/topics/{topic_id}/tools         | 主题下工具         | 否            |
| GET            | /api/v1/topics/{topic_id}/tool-count    | 主题下已发布工具数 | 否            |
| GET/POST       | /api/v1/tools                           | 工具 CRUD          | 仅 POST       |
| GET/PUT/DELETE | /api/v1/tools/{tool_id}                 | 工具详情           | 仅 PUT/DELETE |
| GET/POST       | /api/v1/tools/{tool_id}/links           | 工具链接           | 仅 POST       |
| PUT/DELETE     | /api/v1/tools/{tool_id}/links/{link_id} | 链接详情           | 是            |
| PUT            | /api/v1/tools/{tool_id}/topics          | 工具主题归属       | 是            |
| GET            | /api/v1/env                             | 环境信息           | 否            |
| POST           | /api/v1/export                          | 导出 JSON (会写盘) | 是            |
| GET            | /api/v1/health                          | 健康检查           | 否            |

写操作与 `POST /api/v1/export` 需要 `X-API-Key` 头; 9 个只读接口
(`GET /health` `/env` `/tools` `/tools/{id}` `/tools/{id}/links` `/topics`
`/topics/{id}` `/topics/{id}/tools` `/topics/{id}/tool-count`) 不需要。缺/错 Key → 401。

## 关键约定

- 数据库表前缀 `xg_`, 主键 BIGINT 自增, 业务标识用 slug
- 主要表: `xg_topic` `xg_tool` `xg_tool_topic` `xg_tool_link`
- 标签是 `xg_tool.tags` JSON 列 (字符串数组, 最多 8 个), 不是独立表, 也没有 `/tags` 端点
- 工具 status 是字符串: draft / pending / published / archived
- 主题 status: disabled / active; 链接 status: active / broken / disabled
- pricing: free / freemium / paid; 是否开源是独立字段 `is_open_source`
- 新增必填字段: `tagline` / `origin`(cn|overseas) / `access`(direct|proxy) / `languages`(ISO 639-1 数组, 1~8 项)
- 字段上限 (写入端 422 拦截): `slug` ≤64 且为 kebab (`^[a-z0-9]+(?:-[a-z0-9]+)*$`); 工具 `name` ≤128 / 主题 `name` ≤64, 均非空白; `tagline` 必填 ≤100 且**句末必须是标点**; `description` ≤500 可空; `url` ≤2048
- 主题/工具 `slug` 是对外主键 + URL 片段, **一律不加 `ai-` 前缀**, 直接用语义英文词 (`image-generation` 而非 `ai-image-generation`), 创建后不再更改
- `tags` ≤8 个, 单个 ≤32 字符, 不可重复/为空/首尾带空白; `languages` 1~8 项, 两字母小写 ISO 639-1, 不可重复
- `description` 为 NULL 时导出物**省略该键** (不是输出 null)
- 工具的主题归属用 `topic_ids: [int]` + 可选 `primary_topic_id` (后者必须在 `topic_ids` 里)
- URL 去重通过归一化 + SHA-256 hash; `url` 必须显式带 `http(s)://` (裸域名 `www.example.com` 直接 422, 不会自动补 scheme); **非本地地址必须 https**, `http://` 非本地直接 422 (只有 localhost/127.0.0.1/::1/0.0.0.0 可用 http); 归一化**不做**追踪参数清洗 (`utm_*` / `gclid` / `fbclid` 原样保留), 只排序 query、丢 fragment、去 `www.`
- is_primary 唯一性由应用层保证 (新设主链接会把旧主链接降级, 不报 409)
- 列表接口返回**裸数组**, 总数在响应头 `X-Total-Count` (CLI 不打印响应头, 只在表格尾部打印 `(共 N 条)`); 分页参数是 `page`(≥1) / `page_size` (`tools` ≤100, `topics` ≤200), **不是 `limit`/`offset`**; `/tools/{id}/links` 无分页也无 `X-Total-Count`, 且工具不存在时返回 `[]` 而非 404
- 环境配置: `studio/.env.dev` / `.env.sit` / `.env.prod`, 通过 `APP_ENV` 切换
- `.opencode/commands/*.md` 里的 `` !`...` `` 块在命令被调用时**立即执行** (openCode 用 ``/!`([^`]+)`/g`` 在整份模板上匹配, 不区分代码块), 所以只有无副作用的只读检查才用 `` !` ``; 写操作/带占位符的模板一律用普通代码块

## MySQL MCP 使用规则

三个 MCP server 对应三套环境, 按用户意图选用:

| MCP server   | 环境 | 权限                                                |
| ------------ | ---- | --------------------------------------------------- |
| `mysql-dev`  | dev  | 读写 (`MYSQL_ALLOW_WRITE=true`, 见 `opencode.json`) |
| `mysql-sit`  | sit  | 只读                                                |
| `mysql-prod` | prod | 只读                                                |

- 用户说"开发库/测试库/生产库"时, 对应使用 `mysql-dev` / `mysql-sit` / `mysql-prod`
- prod 默认只读; 如需写操作, 需用户显式确认后修改 `opencode.json` 加 `MYSQL_ALLOW_WRITE`
- 表名前缀 `xg_`, 主要表: `xg_topic` `xg_tool` `xg_tool_topic` `xg_tool_link`
- 工具 status: draft=草稿 pending=待审核 published=已发布 archived=已下架; 合法转换: draft→pending, pending→draft, pending→published, published→archived, archived→published
- 标签在 `xg_tool.tags` JSON 列里, 没有独立的标签表/关联表

## 生产环境保护

执行 skills/tools/api.py 写操作时, CLI 会探测后端 `/api/v1/env`, 若返回 `prod` 则强制门槛
(注意: `STUDIO_URL` 指向 localhost/127.0.0.1/0.0.0.0 时**跳过探测** —— 本地以 `APP_ENV=prod`
起的 studio 不受下面这三条保护):

- 所有写操作必须 `--yes`, 否则拒绝 (exit 3)
- DELETE 操作额外必须 `--prod-confirm`, 否则拒绝 (exit 3)
- 日志醒目记录 `PROD 写操作`

模型在 prod 环境执行任何命令前应:

1. 先确认操作必要性, 优先 dry-run 预览
2. 写操作统一带 `--yes`, 删除类带 `--prod-confirm`
3. 状态变更 (尤其下架/打回) 需用户明确指令, 不可自主执行
