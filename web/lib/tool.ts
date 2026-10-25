import type { Tool, ToolIndex } from "./types"

/** 列表首屏与「加载更多」的每页条数。 */
export const TOOL_PAGE_SIZE = 60

export function getToolDate(tool: Tool): string {
  return tool.publishedAt ?? tool.createdAt ?? ""
}

/** 完整工具 → 列表索引（只保留排序/筛选需要的字段）。 */
export function toToolIndex(tool: Tool): ToolIndex {
  return {
    id: tool.id,
    name: tool.name,
    topics: tool.topics,
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
