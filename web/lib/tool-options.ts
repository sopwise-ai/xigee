import type { LucideIcon } from "lucide-react"
import { ArrowDownAZ, ArrowUpZA, LayoutGrid, List, Sparkles, Star } from "lucide-react"
import type { SortMode, TabMode, ViewMode } from "@/lib/tool-query"

export interface ToolOption<T extends string> {
  value: T
  label: string
  icon: LucideIcon
}

/** 视图模式选项（宫格 / 列表）。工具工具栏与浏览偏好共用。 */
export const VIEW_OPTIONS: readonly ToolOption<ViewMode>[] = [
  { value: "grid", label: "宫格", icon: LayoutGrid },
  { value: "list", label: "列表", icon: List },
]

/**
 * 排序模式选项。工具工具栏与浏览偏好共用。
 *
 * 不再提供「最新」：当前 6,175 条数据的 publishedAt 全部是导入日（2026-10-25），
 * 按日期排序等价于名称排序。保留一个语义不成立的选项只会误导用户；
 * 等数据侧有真实发布时间后再恢复。URL 里的旧 `sort=latest` 会被校验丢弃并回退默认。
 */
export const SORT_OPTIONS: readonly ToolOption<SortMode>[] = [
  { value: "recommended", label: "精选优先", icon: Sparkles },
  { value: "name-asc", label: "名称 A-Z", icon: ArrowDownAZ },
  { value: "name-desc", label: "名称 Z-A", icon: ArrowUpZA },
]

/**
 * Tab 模式选项（全部 / 精选）。
 *
 * 同理移除「最新」：没有真实时间维度的「最新」目前只是名称序，
 * 与排序下拉里的「名称 A-Z」重复且更误导。
 */
export const TAB_OPTIONS: readonly ToolOption<TabMode>[] = [
  { value: "all", label: "全部", icon: LayoutGrid },
  { value: "featured", label: "精选", icon: Star },
]
