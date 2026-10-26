import type { SortMode } from "./tool-query"
import type { Tool, ToolIndex } from "./types"

/** 列表首屏与「加载更多」的每页条数。 */
export const TOOL_PAGE_SIZE = 30

/** 单次 /api/tools 最多返回的完整工具数（与列表每页上限共用）。 */
export const MAX_TOOL_PAGE_SIZE = 100

export function getToolDate(tool: Tool): string {
  return tool.publishedAt ?? tool.createdAt ?? ""
}

/** 完整工具 → 列表索引（只保留排序/筛选需要的字段）。 */
export function toToolIndex(tool: Tool): ToolIndex {
  return {
    id: tool.id,
    name: tool.name,
    featured: tool.featured,
    date: getToolDate(tool),
  }
}

/**
 * 名称比较器（SSG 确定性）：显式指定 zh-CN，避免 localeCompare 默认 locale
 * 在服务端（Node）与客户端（浏览器）不一致导致 hydration mismatch。
 */
const nameCollator = new Intl.Collator("zh-CN", { numeric: true, sensitivity: "base" })

export function compareName(a: Tool, b: Tool): number {
  return nameCollator.compare(a.name, b.name)
}

/** 取日期部分（YYYY-MM-DD），忽略时间与时区，保证跨格式比较的确定性。 */
function dateOnly(value: string): string {
  return value.slice(0, 10)
}

/**
 * 日期倒序比较器（确定性）：仅比较 YYYY-MM-DD 部分，避免混入 ISO 时间后
 * 默认 locale 的 localeCompare 在服务端/客户端产生不一致。空日期排最后。
 */
export function compareDateDesc(a: string, b: string): number {
  const da = dateOnly(a)
  const db = dateOnly(b)
  if (!da && !db) return 0
  if (!da) return 1
  if (!db) return -1
  if (da === db) return 0
  return da < db ? 1 : -1
}

/**
 * 综合排序比较器：精选优先 → 发布日期倒序 → 名称升序（确定性）。
 * 供「全部」tab 默认排序使用，避免与「最新」tab 的纯时间排序语义重复。
 */
export function compareRecommended(a: Tool, b: Tool): number {
  const fa = a.featured ? 1 : 0
  const fb = b.featured ? 1 : 0
  if (fa !== fb) return fb - fa
  const dateCmp = compareDateDesc(getToolDate(a), getToolDate(b))
  if (dateCmp !== 0) return dateCmp
  return compareName(a, b)
}

export function compareIndexName(a: ToolIndex, b: ToolIndex): number {
  return nameCollator.compare(a.name, b.name)
}

export function compareIndexDateDesc(a: ToolIndex, b: ToolIndex): number {
  return compareDateDesc(a.date ?? "", b.date ?? "")
}

export function compareIndexRecommended(a: ToolIndex, b: ToolIndex): number {
  const fa = a.featured ? 1 : 0
  const fb = b.featured ? 1 : 0
  if (fa !== fb) return fb - fa
  const dateCmp = compareIndexDateDesc(a, b)
  if (dateCmp !== 0) return dateCmp
  return compareIndexName(a, b)
}

/** 对轻量索引排序（返回新数组，不改入参）。 */
export function sortToolIndex(index: readonly ToolIndex[], sort: SortMode): ToolIndex[] {
  const list = [...index]
  switch (sort) {
    case "name-asc":
      list.sort(compareIndexName)
      break
    case "name-desc":
      list.sort((a, b) => compareIndexName(b, a))
      break
    case "latest":
      list.sort((a, b) => compareIndexDateDesc(a, b) || compareIndexName(a, b))
      break
    case "recommended":
      list.sort(compareIndexRecommended)
      break
  }
  return list
}

/**
 * 索引的紧凑传输格式：id/name 各一个数组，featured 只存为 true 的下标。
 *
 * 对象数组会为 6,175 条数据重复 4 个键名（约 470 KB）；数组化后约 185 KB，
 * 配合 `/api/index` 的 CDN 缓存，避免把索引塞进 HTML 又保持交互所需的全量排序能力。
 */
export interface ToolIndexPayload {
  ids: string[]
  names: string[]
  featured: number[]
}

export function encodeToolIndex(index: readonly ToolIndex[]): ToolIndexPayload {
  const featured: number[] = []
  index.forEach((tool, i) => {
    if (tool.featured) featured.push(i)
  })
  return {
    ids: index.map((tool) => tool.id),
    names: index.map((tool) => tool.name),
    featured,
  }
}

export function decodeToolIndex(payload: ToolIndexPayload | readonly ToolIndex[]): ToolIndex[] {
  if (Array.isArray(payload)) return payload as ToolIndex[]
  const data = payload as ToolIndexPayload
  const featured = new Set(data.featured ?? [])
  return data.ids.map((id, i) => ({
    id,
    name: data.names[i] ?? "",
    featured: featured.has(i) || undefined,
  }))
}

/**
 * 首屏预取的完整工具集合：只取默认「精选优先」排序的第一页。
 *
 * 以前会预取四种排序 + 精选，最多 5×pageSize 份完整工具（去重后仍 170+ 条），
 * 这些对象全部进入 RSC/HTML，是首屏 1 MB 的重要来源。现在换排序/翻页由 `/api/tools`
 * 按需补齐，首屏只带用户真正看到的 60 条。
 */
export function getInitialToolIds(index: readonly ToolIndex[], pageSize = TOOL_PAGE_SIZE): string[] {
  return sortToolIndex(index, "recommended")
    .slice(0, pageSize)
    .map((tool) => tool.id)
}

/** 一组工具中最新的日期（原始串）；无日期返回 null。按日期部分比较，容忍格式差异。 */
export function latestToolDate(tools: readonly Tool[]): string | null {
  let latest: string | null = null
  for (const tool of tools) {
    const date = getToolDate(tool)
    if (!date) continue
    if (latest === null || dateOnly(date) > dateOnly(latest)) latest = date
  }
  return latest
}

/**
 * 生成 data-history-* 属性所需的最小字段集：结果行（`Tool`）与顶栏搜索建议
 * （`SuggestionDoc`）共用同一套历史埋点，点击 / 键盘回车打开都会被根部 HistoryTracker 记录。
 */
export interface HistoryLinkable {
  id: string
  name: string
  url: string
  topics: readonly string[]
  pricing?: Tool["pricing"]
}

export function toolHistoryAttrs(tool: HistoryLinkable): Record<string, string> {
  return {
    "data-history-id": tool.id,
    "data-history-name": tool.name,
    "data-history-url": tool.url,
    "data-history-topic": tool.topics[0] ?? "",
    "data-history-pricing": tool.pricing ?? "",
  }
}
