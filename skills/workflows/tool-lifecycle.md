# 工具生命周期工作流

## 完整流程

```
1. 采集 (/std-collect)
   → 混乱数据(文本/网页/列表/JSON/CSV) → 批量草稿 (status=draft)
   → 写创建所需必填集(name/slug/tagline/pricing/origin/access/languages + url)，
     描述/主题/标签/附加链接交给后续步骤

2. 补全 (/std-enrich)
   → AI 补全 description、tags、links、topic_ids
   → 仍为草稿 (status=draft)

3. 提交审核 (/std-submit)
   → 校验必填(名 + tagline + 链接) → 进入待审核 (status=pending)

4. 审核 (/std-review)
   → 通过: status=published (已发布), published_at 首次写入
   → 打回: status=draft (草稿)，回到步骤 2 补全

5. 发布 (/std-publish)
   → 草稿两步发布 (draft→pending→published)
   → 已下架重新发布 (archived→published)
   → published_at 仅首次→published 写入

6. 评分 (/std-score)
   → python -m app.scoring --all --apply-topics
   → 闭集分类(主题只能从 xg_topic 里选) + 六维评分 → ai_score (0~1000)
   → ai_score 是导出/列表的唯一排序键；--dry-run 可先看效果
   → 人工复核写 review_score (NULL=未复核)：它不参与排序，只做 few-shot 校准

7. 导出 (/std-export)
   → 仅 status=published 且存在 active 链接的工具导出
   → 产物为 web/data/topics-{env}.json + tools-{env}.json；仅 prod 额外同步 web/data/topics.json + tools.json
   → 响应含 skipped_count / skipped_reasons（被跳过的行数与原因）
   → 提交代码 → Vercel 自动部署

8. 下架/重新发布 (/std-archive)
   → 下架 published→archived, 重新发布 archived→published
   → 已下架工具不导出
```

### 横切动作（随时可调用）

```
/std-verify        全量校对，查有无+对错，出问题清单
/std-list          按状态/搜索列出工具
/std-stats         目录总览统计
```

## 辅助管理

- `/std-manage-tool` 工具 CRUD 闭环（含链接、主题归属、标签）
- `/std-manage-topic` 主题 CRUD 闭环
- `/std-set-tags` 标签管理（列出/查看/设置某工具的标签）

## 状态转换矩阵

| 从 \ 到   | draft 草稿 | pending 待审核 | published 已发布 | archived 已下架 |
| --------- | ---------- | -------------- | ---------------- | --------------- |
| draft     | -          | ✓ 提交         | -                | -               |
| pending   | ✓ 打回     | -              | ✓ 通过           | -               |
| published | -          | -              | -                | ✓ 下架          |
| archived  | -          | -              | ✓ 重新发布       | -               |

> 草稿(draft) 不能直接发布(published)，必须先提交审核(draft→pending)再通过(pending→published)。
> 非法迁移后端返回 409。

## 注意事项

- `published_at` 仅在首次 status→published 时写入，之后不变
- 导出仅包含 status=published **且存在 status=active 链接**的工具
- 工具排序键是 `ai_score DESC → published_at DESC → id ASC`（`ai_score` 由 `python -m app.scoring` 写入，0~1000）；`sort_order` 只剩主题/关联/链接三处（人工编排），工具的 `sort_order` 已删除
- 人工复核 `review_score`（0~1000，NULL=未复核）**不参与排序**，只作为评分管线的 few-shot 校准锚点；改 rubric/权重/模型要递增 `RUBRIC_VERSION` 并重跑
- 导出投影细节: `topics[0]` 即主主题（`is_primary` → `sort_order` → `topic_id` 排序）；工具的 `url` 取 `is_primary=1 且 active` 的链接，取不到则回退首个 active 链接，其余 active 链接进 `links[]`（按 `sort_order DESC, id ASC`）；工具无有效主题归属时 `topics` 为 `["misc"]`，`misc` 主题不存在时导出端会合成一条
- `description` 为 NULL 时导出物**省略该键**（不是输出 null）；`lastUpdatedAt` 取审计列 `updated_at`，恒存在
- 导出响应含 `skipped_count` / `skipped_reasons`，跳过的是缺 slug/name/tagline/url/languages 或 pricing 非法的行
- 主题工具计数（topic-count）仅统计会进导出的工具（published + active 链接），但**删除主题时后端拦截统计所有状态的归属关系**，即 count=0 不保证可删（可能有未发布工具关联）
- 删除工具会级联删除其链接与主题归属；标签是工具字段，随工具消失
- 标签最多 8 个，没有独立实体与端点

## 生产环境保护

后端环境为 prod 时，所有写操作强制门槛:

- 写操作必须显式 `--yes`，否则拒绝 (exit 3)
- DELETE 操作额外必须 `--prod-confirm`，否则拒绝 (exit 3)
- 日志醒目记录 `PROD 写操作`

**模型如何知晓后端环境**: 多数命令的前置检查会调 `api.py health`（`/std-list` 除外），该命令输出含 `env` 字段并在 prod 时显示醒目警示行。模型读到警示后主动带 `--yes`/`--prod-confirm`；若仍遗漏，`_write` 层强制拒绝兜底。

> 已知限制: `_write` 的兜底探测只在 `STUDIO_URL` 指向非 loopback 地址时进行。目标为 `localhost` / `127.0.0.1` / `0.0.0.0` 时跳过探测，本地以 `APP_ENV=prod` 启动的 studio 不会触发 exit 3，只能依赖 `health` 的警示行自觉遵守。访问 prod 请使用非 loopback 地址。

模型在 prod 执行命令前应: 优先 dry-run 预览、写操作带 `--yes`、删除带 `--prod-confirm`、状态变更需用户明确指令。
