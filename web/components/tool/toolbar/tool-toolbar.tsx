"use client"

import type { ReactNode } from "react"
import { PageBar } from "@/components/layout/page-bar"
import { FilterTabs } from "@/components/tool/toolbar/filter-tabs"
import { SortMenu } from "@/components/tool/toolbar/sort-menu"
import { ViewToggle } from "@/components/tool/toolbar/view-toggle"
import type { SortMode, TabMode, ViewMode } from "@/lib/tool-query"

interface ToolToolbarProps {
  view: ViewMode
  tab: TabMode
  sort: SortMode
  onViewChange: (view: ViewMode) => void
  onTabChange: (tab: TabMode) => void
  onSortChange: (sort: SortMode) => void
  /** 有筛选 tabs 的页面（首页）为 true；主题页等为 false，改用 title 插槽。 */
  showTabs?: boolean
  /** 由父级 useId 生成的面板 id，供 tabs 的 aria-controls 关联。 */
  panelId?: string
  /** 左侧自定义内容（无 tabs 时展示，如主题页的「主题图标 + 名称」）。 */
  title?: ReactNode
}

/**
 * 工具工具栏：套统一的二级栏（PageBar）—— 通栏、下边框、桌面吸顶。
 * 左：筛选 tabs（全部/最新/精选）或自定义 title；右：排序下拉 + 视图切换。
 * 各类控件统一为同高（h-8）、同圆角、同边框的胶囊外观。
 */
export function ToolToolbar({
  view,
  tab,
  sort,
  onViewChange,
  onTabChange,
  onSortChange,
  showTabs = true,
  panelId,
  title,
}: ToolToolbarProps) {
  return (
    <PageBar
      width="browse"
      actions={
        <>
          <SortMenu sort={sort} onSortChange={onSortChange} />
          <ViewToggle view={view} onViewChange={onViewChange} />
        </>
      }
    >
      {showTabs ? (
        <FilterTabs tab={tab} onTabChange={onTabChange} panelId={panelId} />
      ) : (
        (title ?? <span className="text-sm font-medium text-muted-foreground">工具</span>)
      )}
    </PageBar>
  )
}
