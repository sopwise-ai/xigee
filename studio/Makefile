# XiGee Studio · 常用命令
#
# APP_ENV 是唯一的环境开关 (dev / sit / prod): 它既决定加载哪个 .env.<APP_ENV>,
# 也决定导出产物的后缀。命令行变量优先, 例如:
#   make db-init APP_ENV=prod
#   make dev PORT=9000
#
# ⚠️ 这个文件【不解析 .env.<APP_ENV>】。服务侧的唯一解析器是 app/core/config.py,
# 监听地址与库凭据都由 app 自己读(见 app/__main__.py 与 app/db_init.py)。
# 以前这里用 sed 又抄了一套 dotenv 规则, 于是下面这几种写法会让 make 与服务拿到
# 不同的值 —— db-init 报 Access denied 而服务连得上, 排查会绕远路:
#   DB_PASSWORD="p@ss word"   引号没剥
#   export DB_USER=alice      整行匹配不上, 拿到空
#   DB_PORT=3306  # 主库     注释尾巴没剥
# 抄第二遍就是错, 别再加回来。
#
# 同理, 这里【没有】把 DB_* 逐个转发给 app 的中间变量: make 本来就会把命令行变量
# (DB_HOST=127.0.0.1 make db-init) 与已导出的环境变量原样放进 recipe 的环境, 转发
# 是多余的; 而转发一旦写成 recipe 前缀, DB_PASSWORD 会被 make 连名带值回显到终端
# 与 CI 日志里(实测: make -n db-init 打出 DB_PASSWORD=hunter2), 与 README 承诺的
# "密码不出现在命令行里"直接矛盾。所以 DB_* 只走环境变量, 别再把值拼回 recipe 行。
# 密码请只写进 .env.<APP_ENV>: 从命令行传(DB_PASSWORD=x make ...)的写法, 无论如何
# 都会出现在 make 自己的 argv 里(ps 对同机其他用户可见)。
#
# 注意 APP_ENV 每个 recipe 都显式写成前缀: make 只自动导出"来自命令行或环境"的变量,
# 下面 APP_ENV ?= dev 是 Makefile 内部的赋值, 不写前缀就不会传给 app(实测如此)。

APP_ENV ?= dev

# 命令行可覆盖 .env.<APP_ENV> 里的监听地址; 留空就整个参数都不传, 交给 app 读配置
HOST ?=
PORT ?=
_HOST_ARG = $(if $(HOST),--host $(HOST),)
_PORT_ARG = $(if $(PORT),--port $(PORT),)

# prod 默认监听所有地址 (由前置的容器/反向代理转发); 要改成只听本机:
#   make prod PROD_HOST=127.0.0.1
PROD_HOST ?= 0.0.0.0

# 测试会 TRUNCATE .env.<APP_ENV> 指向的那 4 张 xg_* 表, conftest.py 里有一道门禁:
# 目标库名字里没有 test 时必须显式放行, 否则 pytest 直接以退出码 3 退出(不碰库)。
# 默认的 dev 库是 10.182.32.31 上的共享 SIT 库, 所以需要显式:
#   make test ALLOW_SHARED_DB=1
# 这个 Makefile 变量不会被 make 自动导出(自动导出只覆盖命令行变量与环境变量),
# 所以必须显式写成 recipe 前缀; 默认空 —— 门禁的默认姿态仍然是"拒绝"。
ALLOW_SHARED_DB ?=

.PHONY: sync db-init dev sit prod lint typecheck format check test test-cov score export-dev export-sit export-prod clean

sync:
	uv sync

# 建表: 整份执行 sql/schema.sql (幂等, 可重复跑)。表结构的权威来源就是那个文件,
# 改表结构要同时改它并重跑这个目标 —— 启动服务不会自动建表。
# 连接信息由 app/core/config.py 解析; 需要本机有 mysql 客户端(与目标库同版本)。
db-init:
	APP_ENV=$(APP_ENV) uv run python -m app.db_init

dev:
	APP_ENV=dev uv run python -m app --reload $(_HOST_ARG) $(_PORT_ARG)

sit:
	APP_ENV=sit uv run python -m app $(_HOST_ARG) $(_PORT_ARG)

prod:
	APP_ENV=prod uv run python -m app --host $(or $(HOST),$(PROD_HOST)) $(_PORT_ARG)

# 与根目录 package.json 的 lint:py 保持同一范围 (app/ + tests/), 避免两套标准
lint:
	uv run ruff check app/ tests/

# 类型检查覆盖 app/ + tests/; tests/ 用放宽的一层(不强制写签名), 阈值与理由都在
# pyproject 的 [tool.mypy] overrides 里
typecheck:
	uv run mypy app/ tests/

format:
	uv run ruff format app/ tests/

check: lint typecheck
	uv run ruff format --check app/ tests/

# 测试连真库: 每个用例前会 TRUNCATE 四张 xg_* 表, 见 tests/conftest.py。
# 必须指向可以随便清空的 dev/sit 库, 且先跑过 make db-init。
# 共享库(如默认 dev)还要显式放行: make test ALLOW_SHARED_DB=1
# APP_ENV 与其它目标同源(默认 dev): APP_ENV=sit make test 跑的就是 .env.sit 那套
# 凭据, 不会被这里写死的值悄悄盖掉(以前写死 dev, 命令行给 sit 也没用); prod 由
# conftest 的门禁无条件拒绝, 不靠这个变量兜。
test:
	APP_ENV=$(APP_ENV) STUDIO_ALLOW_SHARED_DB_TRUNCATE=$(ALLOW_SHARED_DB) uv run pytest -v

test-cov:
	APP_ENV=$(APP_ENV) STUDIO_ALLOW_SHARED_DB_TRUNCATE=$(ALLOW_SHARED_DB) uv run pytest --cov=app --cov-report=term-missing -v

# AI 分类 + 评分: 默认只补 ai_score_at 为空的工具。
# 例: make score ARGS="--limit 10 --dry-run" / make score ARGS="--all --apply-topics"
score:
	APP_ENV=$(APP_ENV) uv run python -m app.scoring $(ARGS)

# 导出产物是【两个文件】: topics-{env}.json / tools-{env}.json
# (prod 额外同步无后缀的 topics.json / tools.json 给前端)。
export-dev:
	APP_ENV=dev uv run python -m app.exporters

export-sit:
	APP_ENV=sit uv run python -m app.exporters

# 会覆盖 web/data/topics.json 与 tools.json —— 那是前端的数据源, 确认要发布时再跑
export-prod:
	APP_ENV=prod uv run python -m app.exporters

clean:
	rm -rf .ruff_cache .pytest_cache .mypy_cache .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
