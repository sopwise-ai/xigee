<!-- 本文件有 2 个 H1：Next 注入的 agent-rules 块自带一个 + 文档标题（机器管理块不可改，故整文件禁用 MD025） -->
<!-- markdownlint-disable MD025 -->
<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

# XiGee Directory — AI 工具发现引擎

## 项目概述

页面以 SSG 为主，列表分页/搜索/建议按需走同源 API；数据源仍是 `data/topics.json` + `data/tools.json`，部署于 Vercel。

## 技术栈

- Next.js 16 (App Router) + React 19 + TypeScript 5
- Tailwind CSS 4 + shadcn/ui (base-nova, neutral)
- fuse.js（服务端搜索索引，客户端只拿当前页结果）、lucide-react（界面图标；**主题图标是 emoji**，见下）
- Vitest + Testing Library（单元测试）
- pnpm 12 + Node 24

## 开发命令

```bash
pnpm dev          # 开发服务器 (http://localhost:3000)
pnpm build        # 构建生产版本
pnpm start        # 生产服务器
pnpm lint         # ESLint
pnpm typecheck    # 类型检查
pnpm test         # 测试
pnpm analyze      # 分析构建产物体积
```

## 环境变量

| 变量                            | 说明                              | 默认值                  |
| ------------------------------- | --------------------------------- | ----------------------- |
| `NEXT_PUBLIC_SITE_URL`          | 站点 URL (sitemap/robots)         | `https://www.xigee.net` |
| `NEXT_PUBLIC_STORAGE_PREFIX`    | 本地存储 key 前缀（变更会丢历史） | `xigee`                 |
| `NEXT_PUBLIC_HISTORY_MAX_ITEMS` | 单用户历史记录上限                | `500`                   |
| `NEXT_PUBLIC_SEARCH_THRESHOLD`  | 模糊搜索灵敏度 (0-1，越小越精确)  | `0.3`                   |

## 目录约定

```
app/          # App Router 页面 + 路由级元数据 (sitemap/robots/manifest/og) + 按需数据 API
components/   # UI 组件 (ui/layout/tool/search/history；主题浏览网格在 search/topic-browse.tsx)
lib/          # 工具函数与类型 (data 读取只在 server 端)
data/         # 数据源 (topics.json + tools.json)
```

## 数据流

`topics.json` + `tools.json` → `lib/data.ts`（server 端 import）→ 页面 Server Component。

列表首屏只下发**轻量索引**（`ToolIndex`：id/name/topics/featured/date，见 `lib/types.ts`）与当前页完整工具；
客户端排序/筛选在索引上完成，缺失的完整字段按页请求：

- `GET /api/tools?ids=a,b,c` — 当前页完整工具（最多 100 个 id）
- `GET /api/search?q=&sort=&page=&pageSize=` — 服务端 Fuse 搜索，分页返回
- `GET /api/suggest?q=` — 顶栏建议，只返回前 6 条

`lib/catalog.ts` 是这些 API 的 server-only 数据层（缓存搜索/建议索引）。client 组件不直接 import
数据文件，也不接收全量工具数组；这样首访不再把 6000+ 条完整工具塞进 RSC payload。

## 数据源（骨架对齐 studio 导出）

数据是两份，键名与 studio 导出产物一致：

- `data/topics.json` —— 主题数组：`{ id, name, icon, description?, toolCount }`
- `data/tools.json` —— 工具数组：`{ id, name, description, url, topics, tags?, pricing?, featured?, publishedAt?, createdAt? }`

`lib/data.ts` 是唯一取数入口（`getAllTopics` / `getAllTools` / `getTopicCounts` / `getStats` 等），
页面与组件都通过它取数。**领域词汇与后端一致**：分类→主题（`Topic`）、产品→工具（`Tool`），
路由是 `/topic/[id]`。

`toolCount` 是**导出端派生字段**（`json_exporter.py` 的 `_fill_tool_counts`）：按 `tools[].topics`
实时聚合，多主题工具会在每个所属主题各计一次，因此 `ΣtoolCount ≠ tools.length` 是正常的。前端另有
自算口径（`getTopicCounts`），两者不一致时只 `console.warn`，渲染一律以自算值为准 —— 这样才不会出现
「导航徽标 12 / 主题页 11」。

### 主题图标是 emoji（studio 侧已对齐）

主题图标就是 emoji 字符，源头是库里 `xg_topic.icon`，经导出进 `topics.json` 的 `icon`：
新增主题只改数据、不动代码。渲染见 `lib/topic-icon-node.tsx` —— emoji 靠 `font-size`（`text-*`）
缩放、自带颜色且不继承 `currentColor`，所以调用方传字号类而不是 Lucide 那种 `size-*`。

studio 侧的取值与默认值都已是 emoji（`sql/schema.sql` 列默认 `'📦'`、`schemas/models.py` 的
`TopicCreate` 默认 `"📦"`、`json_exporter.py` 的 `DEFAULT_TOPIC_ICON = "📦"`）；写主题时 `--icon`
直接给 emoji 字符（如 `💬`），不要再用 Lucide 组件名。

两道防线（都已就位，改动时别删）：

1. `lib/topic-icon-node.tsx` 把疑似旧 Lucide 名（纯 ASCII 单词）兜底成 `📦`，并在**非 production**
   环境告警 —— 兜底是为了不把英文名渲染成一串字母，告警用于开发期发现，且已做模块级去重避免刷日志。
2. `lib/data.test.ts` 断言每个 `topic.icon` 都必须匹配 `\p{Extended_Pictographic}`（真正的 emoji 判据，
   而不是「非 ASCII」—— 后者挡得住 `Box`，却挡不住 `★`、`→` 这类非 ASCII 文字）。所以「导出把 emoji
   覆盖成 `Box`」会让 **CI 变红**、同步 PR 合不进去 —— 这层保证比运行期告警重要得多。

`data/topics.json` 与 `tools.json` 是**生产数据源**：`.husky/pre-commit` 只允许在 `main` / `data/<name>`
分支提交，本地测试用带环境后缀的副本（`topics-dev.json` / `tools-dev.json`，已 gitignore）。

**仍未完成（内容侧）**：现在这两份文件是由旧的单文件 `data.json` 机械拆出来的**过渡数据** ——
85 条工具还没迁进 studio 库，导出成员规则要求的 `tagline`（≤100 字、句末带标点）、`origin`、`access`、
`languages`、`openSource`、至少一条 `status='active'` 链接都还没有。真实 `prod` 导出落地前需要
**先把内容迁进库并补齐这些必填字段**；届时前端要同步处理两处：

- **描述字段**：导出用 `tagline`，现在用 `description`。切换后若不改 `lib/data.ts` 的解析字段，描述会
  **静默**变成空串（卡片出现空白描述行、搜索里描述权重失效）。`lib/data.ts` 已在「有 `tagline` 而无
  `description`」时告警，`lib/data.test.ts` 也断言描述非空，两道一起兜住这个切换点。
- **`pricing: "opensource"`**：studio 的 `Pricing` 枚举只有 `free/freemium/paid`（开源是独立的
  `openSource` 布尔轴），而当前数据里有 3 条 `opensource`（n8n / stable-diffusion / flux）。迁移时必须
  为这 3 条决定映射（例如 `pricing=free` + `openSource=true`），否则导出端会拒。

> 注意：`createdAt` 与 `description` 在 studio 导出契约里**并不存在**（导出只有 `publishedAt` /
> `tagline`）。`lib/tool.ts` 用 `publishedAt ?? createdAt` 兜底，所以现状能跑，但别把这两个键当成
> 「已对齐」的导出字段。

## 关键约定

- 页面为 Server Component，交互组件标记 `"use client"`
- Next.js 16 中 `params` 是 Promise，必须 `await`
- `useSearchParams()` 须包裹 `<Suspense>`
- 页面宽度统一走 `lib/layout.ts` 的 `PAGE_WIDTH` / `pageShell()`（浏览型 `max-w-7xl`、
  内容型 `max-w-6xl`），不要在页面里写 `max-w-*` 字面量
- 外壳 chrome 的宽度：**主区顶栏 `MainHeader` 刻意通栏** —— 面包屑贴主区左缘、搜索与右侧入口
  贴右缘，**不**跟居中的正文同宽。试过收进 `pageShell()` 与正文对齐：宽屏下顶栏内容被压成
  窄窄一条（1920px 下缩进 180px、2560px 下 500px），观感反而更差，已回退。顶栏自身的底色与
  分隔线本来就铺满主区，所以只有内容横跨整条栏。其余外壳照常走 `pageShell()`：`Footer` 与正文
  同宽；移动端顶栏 `Header`、主题条 `SubNav` 只在 <768px 出现（该区间 `max-w-*` 不生效），
  沿用 `pageShell("browse")` 与外壳写法统一即可
- 控件一律用 `components/ui/` 的组件 + 变体（`Button variant="outline"`、`ToggleGroup variant="outline"`…），
  不要手写 `inline-flex h-8 rounded-md border px-2.5 …` 这类与变体等价的类名：全站曾出现
  `toolbarControl`、`iconButton` 等 4 份复制品，改一次圆角要改四处
- 空状态一律用 `Empty`（含"筛选/搜索无结果"，不要另写虚线框 div）；加载占位用 `Skeleton`
- base-ui 有几处默认值与 shadcn/radix **相反**，别以为"注册表原样"就是对的；包装层已按本站预期
  修正，改动前先看 `components/ui/` 里的注释：
  - `Menu.RadioItem` 默认 `closeOnClick = false`（普通 `Menu.Item` 是 `true`）→ 单选菜单
    "选中即关闭"的语义在 `components/ui/dropdown-menu.tsx` 里统一打开；要"选中不关闭"就在
    调用处显式传 `closeOnClick={false}`（`components/ui/dropdown-menu.test.tsx` 守着这条）
  - `Select` 的 `alignItemWithTrigger` 默认 `true`（弹层会盖住触发按钮），要用下拉观感就传 `false`
  - `TabsList` 的 `activateOnFocus` 默认 `false`（方向键只移焦点、不选中），要 radix 那种
    "方向键即切换"就得显式打开
  - `ToggleGroup` 没有 `type="single"`，用 `multiple`（默认 false）+ 始终按数组读 `value`
- 信息页（设置/关于/隐私/条款）宽容器下每个小节切成「标签 13rem + 内容 1fr」，内容列铺到
  页框右边缘：既不留下一条结构性空白，行宽也由列宽自然控制在每行 64 字左右 ——
  不要给正文单独加 `max-w-*` 收窄（那是把空白换了个位置）
- 设置类「一行一个设置」用 shadcn `Field`：`FieldGroup` + `Field orientation="responsive"`
  （标题+说明在左、控件在右，窄容器自动堆叠）；列表/键值行用 `Item`；键帽用 `Kbd`。
  不要「卡片里再套一层带边框的控件卡片」—— 两层方框是之前的主要观感问题
- 多选项控件用 `ToggleGroup` + `spacing={0}` 连成一个分段控件（不要排成一堆独立方框）；
  行列数用容器查询（`@container` + `@2xl:` 等）跟随实际宽度，不要用视口断点 ——
  主区可用宽度会被侧栏折叠/展开改变；列数要与选项数对齐，每组都排满整行、不留空格子
- 页面控制栏统一用 `components/layout/page-bar.tsx`（二级栏）：`h-11` + 下边框 + 左切换器 /
  右辅助控件 + 桌面吸附在顶栏之下。各页放什么由页面决定（信息页放页面导航、首页放筛选与
  排序/视图、历史页放搜索与筛选），但形态必须一致：
  - **永远单行 `h-11`**：切换器横向滚动（自带右缘渐隐提示），辅助控件钉在右侧；不要折行 ——
    折行后手机上会出现 83/111px 高的"栏"，就不是栏了
  - 栏内控件高度对齐 `h-8`（`Button` 默认尺寸、`InputGroup`、`FilterSelect`、
    `ToggleGroup size="default"` 都是 h-8）。注意 **`Button size="sm"` 是 h-7**，比它们矮一档 ——
    历史页的「清除筛选 / 清空全部」现在就是 h-7，属已知档位差异；要严格同高就用默认尺寸。
    输入类控件**定宽**（`sm:w-72` 之类），不要 `flex-1` 撑满整条栏
  - **底色通栏、下边框随内容宽度**：底色铺满主区（吸顶时两侧不漏内容），分隔线收在内容
    容器上 —— 否则信息页（正文 6xl）的下划线会比正文两边各多出 40px，看着"超长"
  - 栏与顶栏/正文之间**要留白**（用外壳 main 的上内边距与调用方下边距），不要抵消上内边距
    去"紧贴顶栏" —— 试过，观感逼仄
- 二级栏里的切换器沿用全站既有语言（选中态 `bg-brand/10 text-brand` 胶囊）：短切换器与
  工具筛选、信息导航、移动端主题条共用同一套样式；长列表导航（>8 项横向滚动）不要改下边线
- 移动端信息页不显示主题条（`SubNav` 内按 `isInfoRoute()` 提前返回），避免两条横栏叠在顶栏下
- 工具卡片点击直接跳转外部网站，无详情页
- **搜索全程在客户端完成，换词 / 排序都不许走 `router.push`**：`lib/search.ts` 建 Fuse 索引
  （`createSearchIndex` 常规 + `createFallbackIndex` 兜底），查询词 / `sort` 一律通过
  `lib/url.ts` 的 `writeSearchParams` 写回地址栏 —— Next 16 给 `history.replaceState` 打过补丁，
  只派发 `ACTION_RESTORE` 同步 Router，`useSearchParams()` 随之更新但**不发 RSC 请求**
  （16.4.0 把这次派发搬进了 `navigator.restore`，语义不变，升级时确认过）。
  走 `router.push` 等于每次换词白跑一趟服务器，而服务端对任意 `?q=` 返回的都是同一份空骨架
  （RSC 载荷里既没有「找到 N 个」也没有「未找到与」），搜索结果 100% 在浏览器里算
- 顶栏搜索建议数据由根布局下发（`buildSuggestionDocs` → `SuggestionDoc`，刻意不含 description，
  约 3.2KB gzip），客户端零请求即可出建议；**不要**让 client 组件直接 import 数据文件
- 搜索页三种状态各有一个主角：空查询 = `SearchLanding`（最近搜索 / 试试这些 / 主题）、
  有结果 = 计数 + 排序 + 结果行（描述走 `snippet()` 给出命中上下文）、
  未找到 = `SearchNoResults`（`findRelated` 的「也许你想找」+ 换词建议 + 主题）。
  「也许你想找」必须同时卡阈值与 `FALLBACK_MAX_SCORE`，否则无关查询会硬凑出噪音
- **搜索建议的 `id` / `role="option"` 必须挂在 `<a>` 上**，不能挂在包一层的 `<li>` 上：
  回车打开靠 `getElementById(activeId).click()`，点 `<li>` 不会激活内部链接（曾因此静默失效）
- 命中高亮只有 `tint`（名称，垫一层淡底、**不加 padding/圆角**）与 `em`（正文，muted→foreground）
  两档。别用品牌色当强调色 —— `--brand` 就等于 `--foreground`，上色等于没上色；
  也别在徽章里再叠一层 `<mark>`，那是纯噪音
- 数据更新：修改 `data/topics.json` / `data/tools.json` → `data/<name>` 分支 PR → 合并 → Vercel 自动部署

## CI

`.github/workflows/web-ci.yml`：push/PR 时执行 `lint → typecheck → test → build`。
