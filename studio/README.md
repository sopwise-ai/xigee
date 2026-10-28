# Studio

[![Studio CI](https://github.com/sopwise-ai/xigee/actions/workflows/studio-ci.yml/badge.svg)](https://github.com/sopwise-ai/xigee/actions/workflows/studio-ci.yml)
[![Python](https://img.shields.io/badge/python-3.13-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green)](../LICENSE)

XiGee (AI 工具目录站) 的数据管理后端:FastAPI + SQLAlchemy 2.0 (async) + MySQL。对外提供主题/工具的 CRUD 接口,并把库里的数据导出成前端直接消费的 JSON。

数据模型只有两个实体:

- 主题 (Topic):导航骨架,受控在 20~30 个,扁平,不做层级
- 工具 (Tool):卡片数据。标签是 `xg_tool.tags` JSON 列,不是独立表,也没有 `/tags` 接口

## 环境要求

| 依赖         | 版本       | 说明                                                                                        |
| ------------ | ---------- | ------------------------------------------------------------------------------------------- |
| Python       | >= 3.13    | `.python-version` 固定 3.13,`uv` 据此挑解释器                                               |
| uv           | >= 0.11.30 | 依赖管理与运行入口 (`make sync` / `uv run`);`[tool.uv] required-version` 会强制,CI 固定同值 |
| MySQL        | 5.7 或 8.0 | dev 库是 5.7,prod 库是 8.0;DDL 只用两边都支持的写法;CI 跑 8.0                               |
| mysql 客户端 | 与库同版本 | 仅 `make db-init` 建表时用到                                                                |

## 数据流

```text
MySQL (xg_topic / xg_tool / xg_tool_topic / xg_tool_link)
  ↑ ↓  Studio CRUD (FastAPI)
      ↓  make export-dev / export-sit / export-prod
web/data/topics-dev.json + tools-dev.json       ← 非 prod 只写带环境后缀的副本
web/data/topics.json     + tools.json           ← prod 额外同步, 前端数据源
```

## 快速开始

```bash
# 1. 准备配置 (.env.<env> 已被 .gitignore 忽略, 不会进版本库)
cp .env.example .env.dev
$EDITOR .env.dev      # 至少填 DB_HOST / DB_NAME / DB_USER / DB_PASSWORD / API_KEY

# 2. 安装依赖
make sync             # 等价于 uv sync

# 3. 建表 (幂等, 可重复执行)
make db-init          # 用 .env.dev 的连接信息执行 sql/schema.sql

# 4. 启动
make dev              # 等价于 APP_ENV=dev uv run python -m app --reload
```

启动日志第一条会打印 `Studio starting [dev] | DB: <host>:<port>/<name>`,用它确认连的是哪个库。

监听地址取自 `.env.<env>` 的 `APP_HOST` / `APP_PORT`(模板里是 `127.0.0.1:8000`),要临时改:

```bash
make dev PORT=9000            # 只改端口
make sit HOST=0.0.0.0         # 只改地址
uv run python -m app --help   # 直接看入口支持的参数
```

## 数据库初始化

建表**必须单独做这一步**,启动服务不会自动建表。

- 权威 DDL 是 `sql/schema.sql`,一共 4 张表;`make db-init` 就是把它整份喂给 mysql 客户端
- 脚本是幂等的 (`CREATE TABLE IF NOT EXISTS` + 幂等种子),重复执行安全
- **但它不是迁移工具**:`CREATE TABLE IF NOT EXISTS` 不会改已存在的表,所以删/改列之后,老库重跑 `db-init` 不会有任何变化(表还在旧结构上,服务会报 `Unknown column`)。仓库刻意没有引入 alembic —— 表结构只有 4 张、且要兼顾 5.7/8.0,加一层迁移框架的收益不抵它的维护面。改列的落地方式二选一:
  - 数据不要了(dev/sit 常见):`DROP TABLE xg_tool_link, xg_tool_topic, xg_tool;` 再 `make db-init`(一条语句里一起删,否则外键会拦住 `xg_tool`)。
  - 要留数据:自己写 `ALTER TABLE`(`CHANGE COLUMN` 改名不会丢数据;`DROP COLUMN` 会)。
  - **本次 `sort_order` → `ai_score` 已备好一次性脚本**:`sql/migrations/20261028_ai_score.sql`。它不幂等,只该跑一次;跑完老库才有评分/复核列,否则服务会报 `Unknown column 'xg_tool.ai_score'`。
- 连接信息按 `APP_ENV` 从 `.env.<APP_ENV>` 读 (默认 `dev`)。**解析器只有 `app/core/config.py` 一个** —— 服务、`db-init`、导出器都走它,Makefile 不再自己解析 `.env`(以前用 sed 抄过一套 dotenv 规则,导致 `DB_PASSWORD="p@ss word"` 这类写法会让 make 与服务拿到不同的值)
- 要临时指向别的库,用环境变量覆盖(`pydantic-settings` 里环境变量优先于 `.env` 文件;make 自己会把命令行变量原样传给 app,不需要 Makefile 再转发一遍):`make db-init DB_HOST=127.0.0.1 DB_PORT=9999 DB_NAME=scratch`
- 密码通过 `MYSQL_PWD` 环境变量传给客户端,不出现在命令行里(`ps` 对同机器其他用户可见)
- 客户端会带上 `--default-character-set=utf8mb4`:脚本里有中文种子数据 (`misc` / `未分类`),不指定字符集会写成乱码

| 表              | 说明                                                                                   | 关系                                                      |
| --------------- | -------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| `xg_topic`      | 主题 (导航骨架)                                                                        | 被 `xg_tool_topic` 外键 RESTRICT,不能直接删还有工具的主题 |
| `xg_tool`       | 工具主表,`tags` / `languages` 都是 JSON 列;`ai_*` 是评分派生列,`review_*` 是人工复核列 | 删除时级联删关联与链接                                    |
| `xg_tool_topic` | 工具-主题 N:M,`is_primary` 标记主主题                                                  | 每个工具至多一个主主题 (app 保证)                         |
| `xg_tool_link`  | 工具链接 1:N,`url` 存的就是归一化后的地址                                              | 每个工具至多一个主链接 (app 保证)                         |

两条容易踩的设计约定:

- **库层没有 CHECK / ENUM**(为兼容 MySQL 5.7 且加值不用 DDL),值域校验全在 `app/schemas` 的 Pydantic 里。绕过 API 直连改库要自己保证取值合法,否则导出会因枚举越界整体中断
- 不用软删除,靠 `status` 管理;导出只取 `topic.status='active'` 与 `tool.status='published'` 且存在 active 链接的行

## 环境变量

模板是 `.env.example` (唯一可提交的 env 文件),`APP_ENV` 决定加载哪个 `.env.<env>`。

**Python 侧只有 `app/core/config.py` 解析这些文件。** Makefile 既不解析、也不转发 `DB_*`(make 自己会把命令行变量与已导出的环境变量原样传进 recipe,理由见 Makefile 顶部注释);`scripts/` 里只有 `scripts/mcp-mysql.sh` 要读同一份文件去喂 MySQL MCP server,它也只按需挑 `DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD` 五个键(不 `source`、不导出 `API_KEY`,且不执行文件里的 `$(...)`)。进程环境变量优先于 `.env` 文件,所以临时覆盖用 `make dev PORT=9000` 或 `DB_NAME=scratch make db-init`。`scripts/` 下其余的脚本连读都不读:studio 的监听端口与 API Key 都由 `scripts/lib.sh` 向 app 问(`studio_port` / `studio_api_key`),不抄第二份解析器。

| 变量                                             | 默认值                                        | 说明                                                                                                                                                                                     |
| ------------------------------------------------ | --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `APP_ENV`                                        | `dev`                                         | `dev` / `sit` / `prod`;决定加载哪个 `.env.<env>`,也决定导出产物后缀。**必须由进程环境变量提供**(`APP_ENV=sit make dev`):写进 `.env.<env>` 不会切换加载的文件,只会覆盖 `Settings.app_env` |
| `APP_DEBUG`                                      | `true`                                        | prod 下必须为 `false`,否则启动直接失败                                                                                                                                                   |
| `APP_HOST` / `APP_PORT`                          | `127.0.0.1` / `8000`                          | `python -m app` 的监听地址(`--host` / `--port` 或 `make dev PORT=9000` 覆盖);`make prod` 默认 `0.0.0.0`                                                                                  |
| `LOG_LEVEL`                                      | `INFO`                                        | 日志级别:`DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL`,大小写不敏感                                                                                                                |
| `DB_HOST` / `DB_PORT`                            | `localhost` / `3306`                          | MySQL 地址                                                                                                                                                                               |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD`            | 空                                            | 必填 (`DB_PASSWORD` 可以是空串);为空时**启动即失败**,不等第一次查询                                                                                                                      |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW`               | `5` / `10`                                    | 连接池;测试进程用 `NullPool`,这两个值不生效                                                                                                                                              |
| `DB_ECHO`                                        | `false`                                       | 打印 SQL;只在本地排查问题时打开                                                                                                                                                          |
| `EXPORT_OUTPUT_DIR`                              | `../web/data`                                 | 导出目录,相对路径按 `studio/` 解析 (与 cwd 无关)                                                                                                                                         |
| `CORS_ORIGINS`                                   | `http://localhost:3000,http://localhost:5173` | 逗号分隔白名单,**`*` 与空值都会被启动校验拒绝**                                                                                                                                          |
| `API_KEY`                                        | `dev-secret-key`                              | 写操作的 `X-API-Key`;`sit` / `prod` 不允许留默认值                                                                                                                                       |
| `LLM_BASE_URL` / `LLM_MODEL`                     | `https://api.deepseek.com` / `deepseek-flash` | 评分管线端点与模型。旧的 `deepseek-chat` 已于 2026-07-24 下线,写旧名会失败                                                                                                               |
| `LLM_API_KEY`                                    | 空                                            | 只有 `python -m app.scoring` 需要;缺它时评分命令以退出码 2 失败                                                                                                                          |
| `LLM_TIMEOUT_SECONDS` / `LLM_MAX_RETRIES`        | `60` / `2`                                    | 单次请求超时(秒) / 网络与限流重试次数                                                                                                                                                    |
| `LLM_MAX_OUTPUT_TOKENS` / `LLM_REASONING_EFFORT` | `4000` / `low`                                | 单次响应上限(含思考 token) / 思考强度 `low`/`high`/`max`。思考模式下没有 temperature                                                                                                     |
| `LLM_STRUCTURED_OUTPUT`                          | `json_schema`                                 | `json_schema`(解码层约束,首选)或 `json_object`(provider 不支持时降级)                                                                                                                    |
| `SCORING_SAMPLES` / `SCORING_CONCURRENCY`        | `3` / `4`                                     | 每个工具采样次数 / 并发请求数                                                                                                                                                            |
| `SCORING_AUTHORITY_WEIGHT`                       | `0.50`                                        | 权威度在最终分里的占比 γ;改它会改变 `ai_score_version`                                                                                                                                   |
| `SCORING_STALE_DAYS`                             | `90`                                          | `--stale-days` 不带数值时的默认天数                                                                                                                                                      |

两个必须知道的坑:

- pydantic-settings 默认 `extra="forbid"`,`.env.<env>` 里出现**未知键**会让服务直接起不来 (`Extra inputs are not permitted`)。已废弃的 `EXPORT_OUTPUT_PATH` 就是这样一个键:改名后只能写 `EXPORT_OUTPUT_DIR`,写错不要以为是注释无效
- `EXPORT_OUTPUT_DIR` 是**目录**不是文件。旧文档里的值形如 `../web/data/data.json`,照抄会建出一个叫 `data.json` 的目录

## 导出产物

一次导出写**两个文件**,不是单个 `data.json`:

| 环境          | 产物                                                                                            |
| ------------- | ----------------------------------------------------------------------------------------------- |
| `dev` / `sit` | `web/data/topics-{env}.json` + `web/data/tools-{env}.json`                                      |
| `prod`        | 上面两个 (`topics-prod.json` / `tools-prod.json`) **再加**无后缀的 `topics.json` + `tools.json` |

```bash
make export-dev      # APP_ENV=dev uv run python -m app.exporters
make export-sit
make export-prod     # 注意: 会覆盖 web/data/topics.json 与 tools.json (前端数据源)
```

也可以用 `POST /api/v1/export` (需要 API Key),返回条数与跳过统计。

- 无后缀的 `topics.json` / `tools.json` 是前端的数据源,只有 `prod` 才同步,dev/sit 刻意不碰
- 输出目录由 `EXPORT_OUTPUT_DIR` 决定 (默认 `../web/data`)
- 成员规则与排序以 `sql/schema.sql` 顶部的【导出投影】为准;字段形状见 `schema/topics.data.jsonc` 与 `schema/tools.data.jsonc` (带注释的格式定义,不是数据集)
- 产物是严格 JSON (UTF-8,2 空格缩进,结尾换行),写入用临时文件 + `os.replace`,不会留下半个文件
- 逐行跳过 (slug/tagline/url 为空,工具没有可用链接) 只记账不中断;枚举取值越界会直接让整次导出失败

## AI 评分与人工复核

`xg_tool` 的排序键不再是人工权重 `sort_order`,而是 AI 评分的派生列 `ai_score`(0~1000):

```
raw      = Σ w_i · (s_i - 1) / 4                        六个维度各 1~5 分(权重见 app/scoring/rubric.py)
quality  = (n·raw + m·prior) / (n + m)                   经验贝叶斯收缩(n=证据条数, m=2, prior=全站中位数)
ai_score = round(((1-γ)·quality + γ·authority/9) · 1000) γ = SCORING_AUTHORITY_WEIGHT(默认 0.50)
```

两根轴刻意分开,不许互相冒充:

- `quality` 回答"它好不好",由 6 个维度合成;资料越全,收缩越轻
- `authority` 回答"它重不重要",取值 0~9:AI 给 `ai_authority`,人工可用 `authority_override` 覆盖
- **资料完整度只影响 quality 的证据收缩,绝不参与 authority 判断** —— 资料残缺但行业地位高的工具不会沉底,资料齐全但本质平庸的工具也不会靠前
- 人工改 `authority_override` 会**立即**用 `ai_score_breakdown` 里的 quality 重算 `ai_score`,不调用模型

重算有五个理由,全部手动触发(`make score`):

| 参数                        | 选中的行                                   |
| --------------------------- | ------------------------------------------ |
| 不带参数                    | 从未评分(`ai_score_at IS NULL`)            |
| `ARGS="--changed"`          | 评分输入的 SHA-256 变了的                  |
| `ARGS="--stale-days"`       | 超过 `SCORING_STALE_DAYS`(默认 90)天没评的 |
| `ARGS="--outdated-version"` | rubric / 模型 / γ 变了的                   |
| `ARGS="--all"`              | 全量                                       |

```bash
make score ARGS="--limit 10 --dry-run"    # 先看效果,不写库
make score ARGS="--changed"               # 内容变了的
make score ARGS="--stale-days"            # 太久的(默认 90 天)
make score ARGS="--all --apply-topics"    # 全量重评并把主题建议写进 xg_tool_topic
```

- **唯一的 AI 写入口**是离线管线,API 与人工都不写 `ai_*`;维度分、权重、采样、quality、γ 全在 `ai_score_breakdown` 里,可复算
- 分类是**闭集**:主题清单来自 `xg_topic`,输出后再按白名单过滤;每次采样投票,半数以上才采用
- 默认采样 3 次(中位数 + 采样一致率),`ai_score_confidence` 是采样一致率 —— 它衡量模型稳不稳定,不衡量分数对不对
- 人工复核写在 `review_score`(NULL=未复核),只作为 few-shot 锚点校准评分,**不参与排序**
- 改了 rubric / 权重 / 模型 / γ 必须让 `ai_score_version` 变一次,否则两套口径的分数会混在一张表里排序

`--dry-run` 会照常调用模型,但最后回滚事务。退出码:0 全部成功 / 1 有工具失败(其余已提交) / 2 配置缺失。

## 鉴权

- 写操作 (`POST` / `PUT` / `DELETE`) 以及 `POST /api/v1/export` 需要请求头 `X-API-Key: <API_KEY>`,缺失或错误返回 401
- 读操作 (`GET`) 不需要鉴权
- `GET /api/v1/env` 目前**无鉴权**,只回 `env` / `debug` 两个非敏感字段;不要往里加任何配置值
- `sit` / `prod` 启动时校验 `API_KEY`:不能为空,不能等于默认的 `dev-secret-key`
- 密钥比较用 `secrets.compare_digest`;`.env.<env>` 已被 `.gitignore` 忽略,API Key 与库密码都只写在那里

```bash
curl -X POST http://127.0.0.1:8000/api/v1/export -H "X-API-Key: $API_KEY"
```

## 路由概览

12 个 path / 20 个 operation (与 `GET /openapi.json` 一致):

| 方法             | 路径                                              | 鉴权         | 说明                                                             |
| ---------------- | ------------------------------------------------- | ------------ | ---------------------------------------------------------------- |
| GET, POST        | `/api/v1/topics`                                  | 读 / 写      | 主题列表 (分页);新建主题                                         |
| GET, PUT, DELETE | `/api/v1/topics/{topic_id}`                       | 读 / 写 / 写 | 详情;更新;删除                                                   |
| GET              | `/api/v1/topics/{topic_id}/tools`                 | 读           | 该主题下的工具 (分页)                                            |
| GET              | `/api/v1/topics/{topic_id}/tool-count`            | 读           | 该主题下**会进导出**的工具数                                     |
| GET, POST        | `/api/v1/tools`                                   | 读 / 写      | 工具列表 (支持 `status` / `topic_id` / `featured` 过滤);新建工具 |
| GET, PUT, DELETE | `/api/v1/tools/{tool_id}`                         | 读 / 写 / 写 | 详情;更新;删除                                                   |
| GET, POST        | `/api/v1/tools/{tool_id}/links`                   | 读 / 写      | 链接列表;新增链接                                                |
| PUT, DELETE      | `/api/v1/tools/{tool_id}/links/{link_id}`         | 写 / 写      | 更新链接;删除链接                                                |
| PUT              | `/api/v1/tools/{tool_id}/topics`                  | 写           | 全量替换工具的主题归属 (没列进来的会被摘掉)                      |
| GET, POST        | `/api/v1/health`, `/api/v1/env`, `/api/v1/export` | - / - / 写   | 探活;当前环境;触发导出                                           |

约定:

- 分页响应带 `X-Total-Count`,响应带 `X-Request-ID` (客户端可传入 `X-Request-ID`,不合法会被换成服务端生成的)
- 列表项 `{tool_id}` / `{topic_id}` 用的是自增 `id`;**导出产物里的 `id` 是 `slug`**,两者不要混
- 库连不上 / 锁等待超时 / 连接池取不到连接返回 503 (不是 500);唯一键冲突返回 409
- 但**库结构没跟上**(少了迁移时的 `Unknown column` / `Table doesn't exist`)返回 **500** `Database schema is out of date`,不是 503 —— 重试不会好,这是"忘了跑 `make db-init` 或迁移"的信号

## 测试

```bash
# 目标库不是专用测试库(库名里没有 test)时必须显式放行, 否则 pytest 以退出码 3 退出
make test ALLOW_SHARED_DB=1
make test-cov ALLOW_SHARED_DB=1   # 加覆盖率; pyproject 里 fail_under = 74
```

- 测试连**真数据库**:`tests/conftest.py` 每个用例前 `TRUNCATE` 四张 `xg_*` 表。必须指向一个可以随便清空的 dev/sit 库,不要指向有数据的库
- `APP_ENV` 与其它目标同源(默认 `dev`):`APP_ENV=sit make test` 跑的就是 `.env.sit` 那套凭据。以前 `make test` 里写死了 `dev`,命令行给 `sit` 会被**静默盖掉**(实测 `APP_ENV=sit make -n test` 打出的是 `APP_ENV=dev`);现在不会了,而 `prod` 由门禁无条件拒绝,不依赖这个变量兜底
- 默认的 dev 库是共享 SIT 库,所以 `conftest.py` 里有一道破坏性门禁:`app_env=prod` 或库名/主机名命中 `prod|prd|production` **永远拒绝**(不接受任何环境变量豁免);库名含 `test` 直接放行;其余情况要设 `STUDIO_ALLOW_SHARED_DB_TRUNCATE=1`(即 `make test ALLOW_SHARED_DB=1`)。门禁在 `TRUNCATE` **之前**退出,不碰库
- 跑测试前同样要先建表 (`make db-init`)
- 测试进程自动用 `NullPool` (见 `app/core/database.py`),避免 pytest-asyncio 每个用例换事件循环时报连接挂到别的 loop
- CI 跑的是本地 **MySQL 8.0** 服务容器(与 prod 同版本,认证插件也是默认的 `caching_sha2_password`),见 `.github/workflows/studio-ci.yml`。这正是 dev 的 5.7 库覆盖不到的那条路径

## 常用命令

| 命令                                             | 作用                                                                                                     |
| ------------------------------------------------ | -------------------------------------------------------------------------------------------------------- |
| `make sync`                                      | `uv sync` 安装/同步依赖                                                                                  |
| `make db-init`                                   | 建表 (`python -m app.db_init`,幂等;需 mysql 客户端)                                                      |
| `make dev` / `sit` / `prod`                      | 按环境启动服务 (`python -m app`)                                                                         |
| `make lint` / `typecheck` / `format`             | ruff 检查 / mypy 类型检查 / ruff 格式化                                                                  |
| `make check`                                     | 上面三项 + 格式校验一起跑 (CI 的 lint 段就是它)                                                          |
| `make test` / `test-cov`                         | 测试 (可带覆盖率);共享库要加 `ALLOW_SHARED_DB=1`                                                         |
| `make score ARGS="..."`                          | AI 分类 + 评分 + 权威度 (默认只补没评过的;`--changed` / `--stale-days` / `--outdated-version` / `--all`) |
| `make export-dev` / `export-sit` / `export-prod` | 导出 JSON                                                                                                |
| `make clean`                                     | 清掉 `.ruff_cache` / `.pytest_cache` / `.mypy_cache` / `.coverage` / `__pycache__`                       |

三个 `make` 目标只是 `uv run python -m <模块>` 的薄封装(它们不解析 `.env`,全靠 app 自己读),所以直接用入口也完全等价:`uv run python -m app --help`、`uv run python -m app.db_init`、`uv run python -m app.exporters`、`uv run python -m app.scoring --help`。

## API 文档

启动后访问:

- Swagger UI: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>

## 文档同步点

改了下面这些地方,记得同步对应文件,否则文档会静默过期:

| 改了什么                                   | 要一起改                                                                                                        |
| ------------------------------------------ | --------------------------------------------------------------------------------------------------------------- |
| 路由 (新增 / 改名 / 删除接口)              | 本文件「路由概览」                                                                                              |
| `app/core/config.py` 的 `Settings` 字段    | `.env.example` 与本文件「环境变量」                                                                             |
| 导出产物命名或目录 (`config.export_paths`) | 本文件「导出产物」,`.env.example` 注释                                                                          |
| 表结构或导出投影 (`sql/schema.sql`)        | `schema/*.data.jsonc`,`app/models`,`app/schemas`                                                                |
| Makefile 目标                              | 本文件「快速开始」「常用命令」「测试」                                                                          |
| 依赖或工具链 (`pyproject.toml`)            | `.github/workflows/studio-ci.yml`(固定 uv 版本),本文件「环境要求」(uv 下限由 `[tool.uv] required-version` 强制) |
| `tests/conftest.py` 的破坏性门禁           | 本文件「测试」,`Makefile` 的 `ALLOW_SHARED_DB`                                                                  |
| `[tool.mypy]` 的 strict 范围或豁免         | 本文件「代码风格」,CI 的 Type check 步骤                                                                        |
| 命令行入口 (`app/__main__.py` / `db_init`) | `Makefile` 目标,本文件「快速开始」「常用命令」                                                                  |

## 代码风格

```bash
make format      # ruff format (app/ tests/)
make lint        # ruff check
make typecheck   # mypy (app/ tests/)
make check       # 上面三项 + 格式校验
```

规则配置在 `pyproject.toml`:line-length 120;除 ruff 默认集外还开了 `S`(bandit)、`ASYNC`(异步函数里的阻塞调用)、`LOG` / `G`(logging 用法)、`PT`(pytest 写法)、`TID`(禁止相对导入)。注释与文档用中文,标点用半角 ASCII。

类型检查是 mypy(`[tool.mypy]`):`app/` 走 `strict = true` 全量;`tests/` 走放宽的一层 —— 只查会真的出错的类型问题,不强制每个用例写签名(pytest 本来就用 fixture 注入参数,全量 strict 在 `tests/` 上是 311 个纯噪音的 `no-untyped-def`)。这一层不是摆设:它已经抓出 `conftest.py` 里 `app_env == "test"` 的**死分支**(`APP_ENV=test` 会被 `Settings` 直接拒绝)、一条替该死分支背书的**假绿用例**、以及 `test_health.py` 里拿字符串冒充 DBAPI 异常。所以别把 `tests/` 从类型门禁里摘出去。

pytest 侧另外两条硬约定:未知 ini 键直接报错 (`--strict-config`),弃用警告一律升级为错误 (`filterwarnings = ["error"]`)。只有已经定位到具体来源、短期修不掉的警告才允许逐条放行 —— 之前这里是 `ignore::DeprecationWarning`,把自己代码里的弃用调用也一起吞了。

## 许可与贡献

studio 是 [XiGee](https://github.com/sopwise-ai/xigee) monorepo 的一部分,许可与协作规则以仓库根目录为准:

- 许可:MIT,见 [`LICENSE`](../LICENSE)
- 提交 PR 前请读 [`CONTRIBUTING.md`](../CONTRIBUTING.md)(含本地环境准备、提交信息规范与 `make test ALLOW_SHARED_DB=1` 这类约定)
- 安全漏洞请走 [`SECURITY.md`](../SECURITY.md) 的私下渠道,不要开公开 issue
- 其它求助与提问见 [`SUPPORT.md`](../SUPPORT.md)
