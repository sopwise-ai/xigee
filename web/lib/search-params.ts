import { ArrowDownAZ, Sparkles, type LucideIcon } from "lucide-react"

/** 搜索结果排序维度。 */
export type SearchSort = "relevance" | "latest" | "name"

export interface SearchSortOption {
  value: SearchSort
  label: string
  icon: LucideIcon
}

/**
 * 排序选项：默认「相关度」（Fuse 打分序），另给「名称」。
 * 「最新」已下线：当前数据没有真实发布时间，按日期排等价于名称序。
 */
export const SEARCH_SORT_OPTIONS: readonly SearchSortOption[] = [
  { value: "relevance", label: "相关度", icon: Sparkles },
  { value: "name", label: "名称 A-Z", icon: ArrowDownAZ },
]

const VALID_SORTS: ReadonlySet<string> = new Set(SEARCH_SORT_OPTIONS.map((o) => o.value))

export function isSearchSort(value: string | null): value is SearchSort {
  return value !== null && VALID_SORTS.has(value)
}

/** 搜索页的 URL 状态：查询词 / 排序。两者都写进地址栏，链接可分享。 */
export interface SearchUrlState {
  query: string
  sort: SearchSort
}

/** 搜索结果 facets：主题 / 价格 / 只看精选。空串表示不筛。 */
export interface SearchFacets {
  topic: string
  pricing: string
  featured: boolean
}

export const SEARCH_PRICING_OPTIONS = [
  { value: "", label: "全部价格" },
  { value: "free", label: "免费" },
  { value: "freemium", label: "免费增值" },
  { value: "paid", label: "付费" },
  { value: "opensource", label: "开源" },
] as const

const VALID_PRICING = new Set<string>(SEARCH_PRICING_OPTIONS.map((option) => option.value))

/** 从 URL 读取 facets；未知价格回退「全部价格」。 */
export function readSearchFacets(params: SearchParamsLike): SearchFacets {
  const pricing = params.get("pricing") ?? ""
  return {
    topic: params.get("topic") ?? "",
    pricing: VALID_PRICING.has(pricing) ? pricing : "",
    featured: params.get("featured") === "1",
  }
}

/** 只需要「能按 key 取值」：Next 的 ReadonlyURLSearchParams 也满足。 */
export interface SearchParamsLike {
  get(key: string): string | null
}

export function readSearchState(params: SearchParamsLike): SearchUrlState {
  const sort = params.get("sort")
  return {
    query: params.get("q") ?? "",
    sort: isSearchSort(sort) ? sort : "relevance",
  }
}
