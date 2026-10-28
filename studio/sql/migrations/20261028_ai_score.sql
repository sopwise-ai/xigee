-- ============================================================================
-- 2026-10-28 · xg_tool.sort_order → ai_score，并引入评分元数据、权威度与人工复核列
-- ----------------------------------------------------------------------------
-- 为什么需要这个文件：
--   sql/schema.sql 用的是 CREATE TABLE IF NOT EXISTS，它【不会】改已存在的表。
--   老库（dev/sit/prod）重跑 make db-init 只会被静默跳过，然后服务在第一次查询时
--   报 Unknown column 'xg_tool.ai_score'。仓库刻意没有引入 alembic（4 张表的收益
--   不抵维护面），所以改列这件事只能靠这个一次性脚本。
--
-- 执行方式（在 studio/ 下，连接信息与 db-init 同一套解析器）：
--   mysql --host="$DB_HOST" --port="$DB_PORT" --user="$DB_USER" \
--         --default-character-set=utf8mb4 "$DB_NAME" < sql/migrations/20261028_ai_score.sql
--   或： MYSQL_PWD=... mysql ... < sql/migrations/20261028_ai_score.sql
--
-- 幂等性：**不幂等**。重复执行会在第一个 CHANGE COLUMN 处报 1054/1060。
--   这是刻意的 —— 迁移只该跑一次，静默跳过比报错更危险。
--
-- 兼容性：MySQL 5.7 / 8.0 都支持 CHANGE COLUMN、ADD COLUMN ... AFTER、
--   同一条 ALTER 里 DROP INDEX + ADD KEY。DECIMAL(3,2) 与 JSON 两边都有
--   （5.7.8+ 原生 JSON；dev 库满足）。
--
-- ⚠ 数据语义：CHANGE COLUMN 会保留原值。旧的人工权重（比如 100）会原样变成
--   ai_score=100（即 100/1000），那是【语义错位】而不是迁移成功。所以最后一步
--   显式归零：在第一次真正跑 AI 评分之前，所有工具都回到 0 分，排序回退到
--   published_at DESC, id ASC（比让旧权重冒充 AI 分更安全）。
--   如果你希望保留旧权重当占位，注释掉最后那条 UPDATE，并在部署后立刻跑：
--     uv run python -m app.scoring --all --force
--
-- ⚠ 新增的三列都有默认值/NULL，不需要回填：
--   ai_authority=5（中性）、authority_override=NULL（不覆盖）、
--   ai_score_input_hash=NULL（下次 --changed 时会被视为"需要评分"）。
-- ============================================================================

ALTER TABLE xg_tool
  -- 列重命名：sort_order → ai_score，类型从 INT 收窄到 SMALLINT（0~1000 足够）
  CHANGE COLUMN sort_order ai_score SMALLINT NOT NULL DEFAULT 0
    COMMENT 'AI 评分 0~1000（越大越靠前）；派生值，唯一排序依据',

  -- 评分元数据：没有这几列，分数既不可解释也不可复现
  ADD COLUMN ai_score_confidence DECIMAL(3,2) DEFAULT NULL
    COMMENT '评分置信度 0.00~1.00（N 次采样一致率）；不导出' AFTER ai_score,
  ADD COLUMN ai_score_breakdown JSON DEFAULT NULL
    COMMENT '维度分/权重/采样明细；复算与复核依据，不导出' AFTER ai_score_confidence,
  ADD COLUMN ai_score_version VARCHAR(32) DEFAULT NULL
    COMMENT '评分口径签名（模型+rubric+权威度占比）；不导出' AFTER ai_score_breakdown,
  ADD COLUMN ai_score_at DATETIME DEFAULT NULL
    COMMENT '上次评分时间（NULL=从未评分）；不导出' AFTER ai_score_version,
  ADD COLUMN ai_topics JSON DEFAULT NULL
    COMMENT 'AI 主题分类建议 [{slug,confidence}]；不导出' AFTER ai_score_at,
  ADD COLUMN ai_authority SMALLINT NOT NULL DEFAULT 5
    COMMENT 'AI 判断的行业权威度 0~9（越高越靠前）；派生值，不导出' AFTER ai_topics,
  ADD COLUMN ai_score_input_hash CHAR(64) DEFAULT NULL
    COMMENT '评分输入的 SHA-256（判断内容是否变化）；不导出' AFTER ai_authority,

  -- 人工数据：AI 管线不写这两类列
  ADD COLUMN authority_override SMALLINT DEFAULT NULL
    COMMENT '人工覆盖的权威度 0~9（NULL=不覆盖）；改它可即时重算 ai_score，不导出' AFTER ai_score_input_hash,
  ADD COLUMN review_score SMALLINT DEFAULT NULL
    COMMENT '人工复核分 0~1000（NULL=未复核）；不参与排序、不导出' AFTER authority_override,
  ADD COLUMN reviewed_at DATETIME DEFAULT NULL
    COMMENT '人工复核时间（不导出）' AFTER review_score,
  ADD COLUMN reviewed_by VARCHAR(64) DEFAULT NULL
    COMMENT '复核人标识（不导出）' AFTER reviewed_at,

  -- 索引跟着列名走：排序路径变成 status 等值 + ai_score 降序
  DROP INDEX idx_tool_status_sort,
  ADD KEY idx_tool_status_score (status, ai_score);

-- 旧的人工权重不能冒充 AI 分（见文件头「数据语义」）
UPDATE xg_tool SET ai_score = 0 WHERE ai_score_at IS NULL;

-- 自检：应当看到 ai_score ~ reviewed_by 共 12 列，以及 idx_tool_status_score
SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'xg_tool'
ORDER BY ORDINAL_POSITION;

SELECT INDEX_NAME, COLUMN_NAME, SEQ_IN_INDEX
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'xg_tool'
ORDER BY INDEX_NAME, SEQ_IN_INDEX;
