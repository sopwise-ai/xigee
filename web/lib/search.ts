import Fuse from "fuse.js"
import type { Tool } from "./types"

const DEFAULT_THRESHOLD = 0.3

/**
 * 解析搜索阈值环境变量：未设/空白 → 默认 0.3；
 * 合法数字（含 0）限制到 [0,1] 后使用，非法值回退默认。
 * 注意不能用 `||`，否则 `NEXT_PUBLIC_SEARCH_THRESHOLD=0` 会被错误地视为 falsy。
 */
export function resolveThreshold(): number {
  const raw = process.env.NEXT_PUBLIC_SEARCH_THRESHOLD
  if (raw === undefined || raw.trim() === "") return DEFAULT_THRESHOLD
  const n = Number(raw)
  if (!Number.isFinite(n)) return DEFAULT_THRESHOLD
  return Math.min(1, Math.max(0, n))
}

/**
 * 可搜索的工具文档：在 Tool 之外预计算 `topicNames`，
 * 让「对话」这类主题词也能命中所属工具（Fuse 不能直接索引数组映射）。
 */
export interface SearchDoc extends Tool {
  topicNames: string[]
}

/** 把工具 + 主题名映射展开为可索引文档。 */
export function buildSearchDocs(
  tools: readonly Tool[],
  topicNames: Readonly<Record<string, string>> = {},
): SearchDoc[] {
  return tools.map((t) => ({
    ...t,
    topicNames: t.topics.map((id) => topicNames[id]).filter((name): name is string => Boolean(name)),
  }))
}

/**
 * 顶栏建议（搜索建议下拉）用的精简文档。
 *
 * 刻意不带 `description`：它占了工具数据的四成体积，而下拉只展示「名称 + 主题 + 域名」。
 * 建议索引只在服务端构建（`lib/catalog.ts`），客户端按查询走 `/api/suggest`，
 * 不再随根布局一次性下发 6000+ 条索引。
 */
export interface SuggestionDoc {
  id: string
  name: string
  url: string
  topics: string[]
  topicNames: string[]
  tags?: string[]
  /** 与 Tool 同源，供 data-history-* 记录访问历史（见 toolHistoryAttrs）。 */
  pricing?: Tool["pricing"]
}

/** 工具 + 主题名 → 顶栏建议文档。与 buildSearchDocs 同源，保证两处主题名一致。 */
export function buildSuggestionDocs(
  tools: readonly Tool[],
  topicNames: Readonly<Record<string, string>> = {},
): SuggestionDoc[] {
  return tools.map((t) => ({
    id: t.id,
    name: t.name,
    url: t.url,
    topics: t.topics,
    topicNames: t.topics.map((id) => topicNames[id]).filter((name): name is string => Boolean(name)),
    tags: t.tags,
    pricing: t.pricing,
  }))
}

/** 顶栏下拉最多展示的条数：够用又不至于盖住整块内容。 */
export const SUGGEST_LIMIT = 6

/** 建议索引按「数据数组身份」缓存：布局每次渲染传的是同一数组，索引只在首建时付一次代价。 */
const suggestionIndexCache = new WeakMap<readonly SuggestionDoc[], Fuse<SuggestionDoc>>()

/** 取（必要时构建）建议索引。只在服务端使用；按数组身份缓存，避免每次请求重建。 */
export function getSuggestionIndex(docs: readonly SuggestionDoc[]): Fuse<SuggestionDoc> {
  const cached = suggestionIndexCache.get(docs)
  if (cached) return cached
  const index = createSuggestionIndex(docs)
  suggestionIndexCache.set(docs, index)
  return index
}

/**
 * 建议索引：只索引 名称 / 标签 / 主题名（不含描述，理由见 SuggestionDoc）。
 * 权重向名称倾斜——下拉是「快速点选」，用户敲的多半是工具名。
 */
export function createSuggestionIndex(docs: readonly SuggestionDoc[]): Fuse<SuggestionDoc> {
  return new Fuse([...docs], {
    keys: [
      { name: "name", weight: 0.5 },
      { name: "tags", weight: 0.3 },
      { name: "topicNames", weight: 0.2 },
    ],
    threshold: resolveThreshold(),
    ignoreLocation: true,
    includeScore: true,
  })
}

/** 取前 N 条建议；空查询直接返回空，避免下拉在输入框为空时闪一下。 */
export function suggest(index: Fuse<SuggestionDoc>, query: string, limit = SUGGEST_LIMIT): SuggestionDoc[] {
  const trimmed = query.trim()
  if (!trimmed) return []
  return index.search(trimmed, { limit }).map((r) => r.item)
}

/**
 * 把文本按查询词切分为「命中/未命中」片段，供 UI 高亮。
 * 按空白拆词、忽略大小写，返回可渲染的片段数组；无有效词时返回整段。
 */
export interface HighlightSegment {
  text: string
  match: boolean
}

export function highlightSegments(text: string, query: string): HighlightSegment[] {
  const terms = query
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .filter((t) => t.length > 0)
  if (!text || terms.length === 0) return [{ text, match: false }]

  const lower = text.toLowerCase()
  // 收集所有命中区间
  const ranges: [number, number][] = []
  for (const term of terms) {
    let from = 0
    while (from <= lower.length - term.length) {
      const idx = lower.indexOf(term, from)
      if (idx === -1) break
      ranges.push([idx, idx + term.length])
      from = idx + term.length
    }
  }
  if (ranges.length === 0) return [{ text, match: false }]

  // 合并重叠区间后切片
  ranges.sort((a, b) => a[0] - b[0])
  const merged: [number, number][] = []
  for (const [start, end] of ranges) {
    const last = merged[merged.length - 1]
    if (last && start <= last[1]) last[1] = Math.max(last[1], end)
    else merged.push([start, end])
  }

  const segments: HighlightSegment[] = []
  let cursor = 0
  for (const [start, end] of merged) {
    if (start > cursor) segments.push({ text: text.slice(cursor, start), match: false })
    segments.push({ text: text.slice(start, end), match: true })
    cursor = end
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor), match: false })
  return segments
}

/**
 * 创建模糊搜索索引。维度与权重：名称 0.4 / 描述 0.3 / 标签 0.3 / 主题名 0.2。
 * threshold 越小越精确（见 resolveThreshold）。可传已展开的 SearchDoc 或原始 Tool（内部展开）。
 */
export function createSearchIndex(
  tools: readonly Tool[] | readonly SearchDoc[],
  topicNames: Readonly<Record<string, string>> = {},
  threshold: number = resolveThreshold(),
): Fuse<SearchDoc> {
  const docs = (tools as readonly Tool[]).every((t) => "topicNames" in t)
    ? (tools as readonly SearchDoc[])
    : buildSearchDocs(tools, topicNames)

  return new Fuse(docs, {
    keys: [
      { name: "name", weight: 0.4 },
      { name: "description", weight: 0.3 },
      { name: "tags", weight: 0.3 },
      { name: "topicNames", weight: 0.2 },
    ],
    threshold,
    ignoreLocation: true,
    includeScore: true,
  })
}

/** 兜底索引的阈值下限：比常规搜索松一档，用来回答「你是不是想找…」。 */
export const FALLBACK_THRESHOLD = 0.6

/**
 * 「也许相关」的分数上限。阈值只管匹配容差，最终打分仍可能很高 —— 只用阈值的话
 * `asdfgh` 会凑出「Ada Health」这种纯噪音。实测 0.55 的分界刚好：
 *
 * - 有意义：`跑图` → DALL·E 3、`画图` → DALL·E 3、`写代码` → Codeium / GitHub Copilot
 * - 仍然为空（不硬凑）：`asdfgh`、`qwerty`、`区块链`、`外卖`、`天气`、`股票`
 *
 * 也就是说它只在「确实沾边」时说话，否则把兜底让给精选推荐。
 */
export const FALLBACK_MAX_SCORE = 0.55

/**
 * 兜底索引：正常搜索「未找到」时再搜一次，把「差一点就中」的结果捞出来。
 *
 * 敲错一个字或换了个说法时，用户不该直接撞进死路。阈值取
 * `max(常规阈值, 0.6)` —— 环境变量把常规阈值调得更松时跟随它，不会比常规还严。
 */
export function createFallbackIndex(
  tools: readonly Tool[] | readonly SearchDoc[],
  topicNames: Readonly<Record<string, string>> = {},
): Fuse<SearchDoc> {
  return createSearchIndex(tools, topicNames, Math.max(resolveThreshold(), FALLBACK_THRESHOLD))
}

/** 在兜底索引上取「确实沾边」的前 N 条（按 `FALLBACK_MAX_SCORE` 卡分数）。 */
export function findRelated(index: Fuse<SearchDoc>, query: string, limit = 6): SearchDoc[] {
  const trimmed = query.trim()
  if (!trimmed) return []
  return index
    .search(trimmed)
    .filter((r) => (r.score ?? 1) <= FALLBACK_MAX_SCORE)
    .slice(0, limit)
    .map((r) => r.item)
}

/**
 * 从长文本里截出「命中上下文」：围绕最早出现的那个查询词截取前后各 `window` 个字符，
 * 两端按需补省略号；没有命中就退化成从头截断。
 *
 * 结果页此前直接 `truncate` 描述，命中词落在中后段时用户根本看不到「为什么命中」——
 * 这是搜索结果最伤可用性的一处。
 */
export function snippet(text: string, query: string, window = 18): string {
  if (!text) return ""
  const lower = text.toLowerCase()
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean)

  let hitStart = -1
  let hitEnd = -1
  for (const term of terms) {
    const idx = lower.indexOf(term)
    if (idx !== -1 && (hitStart === -1 || idx < hitStart)) {
      hitStart = idx
      hitEnd = idx + term.length
    }
  }

  if (hitStart === -1) return text.length > window * 2 ? `${text.slice(0, window * 2)}…` : text

  const start = Math.max(0, hitStart - window)
  const end = Math.min(text.length, hitEnd + window)
  return `${start > 0 ? "…" : ""}${text.slice(start, end)}${end < text.length ? "…" : ""}`
}

/**
 * 「把焦点交给结果列表」的全局事件名。
 *
 * 搜索框在顶栏、结果列表在页面里，两者没有共同祖先（布局 vs 页面），
 * 用一个自定义事件解耦比拉一层 Context 更轻。搜索框在搜索页按 ↓ 时派发。
 */
export const SEARCH_FOCUS_RESULTS_EVENT = "xigee:search-focus-results"

/** 结果行的选择器：列表内 ↑↓ 移动焦点、顶栏 ↓ 进入列表都用它定位，避免两处选择器写歪。 */
export const SEARCH_RESULT_SELECTOR = "[data-search-result]"

/**
 * 命中查询词的标签（最多 `limit` 个）。
 *
 * 结果行右侧此前固定显示前两个标签，命中与否全看运气；改成优先显示真正命中的标签，
 * 用户一眼就能确认「这条为什么被搜出来」。没有命中标签时调用方回落到主题名。
 */
export function matchedTags(tags: readonly string[] | undefined, query: string, limit = 2): string[] {
  if (!tags || tags.length === 0) return []
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  if (terms.length === 0) return []
  return tags.filter((tag) => terms.some((term) => tag.toLowerCase().includes(term))).slice(0, limit)
}
