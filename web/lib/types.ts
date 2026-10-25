export const PRICINGS = ["free", "freemium", "paid", "opensource"] as const

export type Pricing = (typeof PRICINGS)[number]

/**
 * 主题（后端 `xg_topic` / 导出 `topics.json` 的元素）。
 * `icon` 是 emoji 字符；`toolCount` 是导出端聚合的派生字段（前端另有自算口径，见 `lib/data.ts`）。
 */
export interface Topic {
  id: string
  name: string
  icon: string
  description?: string
  toolCount?: number
}

/**
 * 列表索引所需的工具元数据。
 *
 * 首页/主题页只把这份轻量索引下发给客户端排序与筛选；完整字段（描述、标签、价格、URL）
 * 按页通过 `/api/tools?ids=` 取，避免一次把 6000+ 条完整工具塞进 RSC payload。
 */
export interface ToolIndex {
  id: string
  name: string
  featured?: boolean
  /** `publishedAt ?? createdAt`，用于「最新」排序；空串表示没有日期。 */
  date?: string
}

/** 工具（后端 `xg_tool` / 导出 `tools.json` 的元素）。 */
export interface Tool {
  id: string
  name: string
  description: string
  url: string
  topics: string[]
  tags?: string[]
  pricing?: Pricing
  featured?: boolean
  publishedAt?: string
  createdAt?: string
}

export interface SiteData {
  topics: Topic[]
  tools: Tool[]
}
