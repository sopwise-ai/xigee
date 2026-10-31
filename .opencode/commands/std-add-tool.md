---
description: 添加 AI 工具到目录（创建为草稿状态）
---

# 添加工具

用户要添加的工具信息: $ARGUMENTS

## 前置检查

先确认 studio 服务可用:

```
!`python skills/tools/api.py health`
```

如果连接失败，告知用户需先启动 studio: `./scripts/dev-studio.sh`

## 你的任务

1. 从用户输入解析工具名称和可选 URL
2. 工具默认创建为草稿状态 (status=draft)
3. 如果用户提供了 URL，自动作为主链接

## 执行步骤

1. 查询现有主题，判断工具归属:

   ```
   !`python skills/tools/api.py topics --page-size 200 --json`
   ```

2. 重复检测: 同时 `tools` 查库内是否已存在同名（忽略大小写）工具。已存在则告知用户并停止，不发起创建请求。

3. 如果主题列表为空，询问用户是否先创建主题 (`/std-add-topic`)

4. 创建工具。以下 5 个参数必填: `--tagline` `--pricing` `--origin` `--access` `--languages`
   （缺任意一个时 CLI 的 argparse 直接 exit 2 并列出缺哪几个，请求根本不会发出；
   后端 422 只用于取值非法，例如 `--tagline` 句末没有标点）

   ```
   python skills/tools/api.py add-tool --name "工具名" --tagline "一句话简介。" --pricing free --origin cn --access direct --languages zh,en
   ```

   可选参数（仅在用户提供时追加）:
   - `--url "https://..."` — 工具官网主链接
   - `--slug "english-slug"` — 自定义 slug；**中文名务必显式传**: 纯中文名自动生成的是
     `item-<8位hex>`，带 ASCII 前缀的中文名会被截成 ASCII 残段（`FT测试工具无名` → `ft`，极易 409）；
     且**不加 `ai-` 前缀**，直接用语义英文词（创建后不再更改）
   - `--topic-ids 1,2,3` — 逗号分隔的主题 ID（支持多主题）
   - `--primary-topic-id 1` — 主主题，必须在 `--topic-ids` 里
   - `--tags a,b` — 逗号分隔标签，最多 8 个
   - `--open-source` — 标记为开源（与 `--pricing` 正交）
   - `--featured` — 标记为精选
   - `--description "较长说明"` — 补充描述
   - `--sort-order <N>` — 排序权重
   - `--status draft|pending` — 新建状态，默认 `draft`（CLI 只接受这两个值）

   取值约束:
   - `--pricing` 仅接受 `free` / `freemium` / `paid`（`opensource` 已移除，开源与否用 `--open-source`）
   - `--origin` 仅 `cn` / `overseas`
   - `--access` 仅 `direct` / `proxy`
   - `--languages` 为 ISO 639-1 两字母小写，1~8 项，逗号分隔

5. 告知用户工具已创建为草稿，可用 `/std-enrich` 补全信息或 `/std-submit` 提交审核
