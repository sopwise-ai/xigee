export type TabMode = "all" | "latest" | "featured"
export type ViewMode = "list" | "grid"
export type SortMode = "recommended" | "latest" | "name-asc" | "name-desc"

export const VALID_TABS: ReadonlySet<string> = new Set<TabMode>(["all", "featured"])
export const VALID_VIEWS: ReadonlySet<string> = new Set<ViewMode>(["list", "grid"])
export const VALID_SORTS: ReadonlySet<string> = new Set<SortMode>(["recommended", "name-asc", "name-desc"])

/** 旧版 URL 别名（?filter=featured/latest）→ tab，用于向后兼容。 */
const FILTER_TO_TAB: Record<string, TabMode> = { featured: "featured", latest: "all" }

export interface UrlState {
  tab: TabMode | null
  view: ViewMode | null
  sort: SortMode | null
}

export function isValidView(value: string): value is ViewMode {
  return VALID_VIEWS.has(value)
}

export function isValidSort(value: string): value is SortMode {
  return VALID_SORTS.has(value)
}

export function isValidTab(value: string): value is TabMode {
  return VALID_TABS.has(value)
}

/** 解析 URL 查询为 tab/view/sort；非法值与旧别名均归一化。 */
export function readUrlParams(search: string): UrlState {
  const qs = new URLSearchParams(search)
  const tabParam = qs.get("tab")
  const filterParam = qs.get("filter")
  const viewParam = qs.get("view")
  const sortParam = qs.get("sort")

  const tab: TabMode | null =
    tabParam && VALID_TABS.has(tabParam)
      ? (tabParam as TabMode)
      : filterParam && Object.hasOwn(FILTER_TO_TAB, filterParam)
        ? FILTER_TO_TAB[filterParam]
        : null

  return {
    tab,
    view: viewParam && isValidView(viewParam) ? viewParam : null,
    sort: sortParam && isValidSort(sortParam) ? sortParam : null,
  }
}

/**
 * 解析初始 Tab。展示 Tab 的页面按 URL > 本地偏好 > 默认；不展示 Tab 的页面
 * （如主题页）完全忽略 URL 与本地偏好，恒用 defaultTab，避免「无切换入口却被静默过滤」。
 */
export function resolveInitialTab({
  urlTab,
  storedTab,
  defaultTab,
  showTabs,
}: {
  urlTab: TabMode | null
  storedTab: TabMode | null
  defaultTab: TabMode
  showTabs: boolean
}): TabMode {
  if (!showTabs) return defaultTab
  return urlTab ?? storedTab ?? defaultTab
}
