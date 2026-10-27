"use client"

import { useEffect, useRef, type KeyboardEvent } from "react"
import { cn } from "@/lib/utils"
import { TAB_OPTIONS } from "@/lib/tool-options"
import type { TabMode } from "@/lib/tool-query"

interface FilterTabsProps {
  tab: TabMode
  onTabChange: (tab: TabMode) => void
  /** 面板 id（与 tabpanel 关联，避免同页多实例冲突）。 */
  panelId?: string
}

/**
 * 工具筛选：全部 / 最新 / 精选，胶囊分段控件（对齐信息区子导航的视觉语言）。
 * 每项为 button 而非 link（会话级筛选，体现在 URL query），选中态 bg-brand/10 + 品牌色。
 * 遵循 WAI-ARIA tabs 键盘约定：←/→/Home/End 在选项间移动焦点并选中。
 * 窄屏放不下时横向滚动，并把选中项自动滚入可视区（否则「精选」可能在屏幕外，看不到当前位置）。
 */
export function FilterTabs({ tab, onTabChange, panelId }: FilterTabsProps) {
  const listRef = useRef<HTMLDivElement>(null)

  // 用瞬时滚动而非 smooth：切 tab 会同时触发列表重排，平滑动画会被浏览器中断，位置就不准了
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')
    el?.scrollIntoView({ inline: "center", block: "nearest" })
  }, [tab])

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const index = TAB_OPTIONS.findIndex((o) => o.value === tab)
    if (index === -1) return

    let nextIndex: number | null = null
    switch (event.key) {
      case "ArrowRight":
        nextIndex = (index + 1) % TAB_OPTIONS.length
        break
      case "ArrowLeft":
        nextIndex = (index - 1 + TAB_OPTIONS.length) % TAB_OPTIONS.length
        break
      case "Home":
        nextIndex = 0
        break
      case "End":
        nextIndex = TAB_OPTIONS.length - 1
        break
      default:
        return
    }

    event.preventDefault()
    const next = TAB_OPTIONS[nextIndex]
    onTabChange(next.value)
    const buttons = event.currentTarget.querySelectorAll<HTMLButtonElement>("[role='tab']")
    buttons[nextIndex]?.focus()
  }

  return (
    <div
      ref={listRef}
      role="tablist"
      aria-label="工具筛选"
      onKeyDown={handleKeyDown}
      // 不自己做滚动容器：滚动交给外层二级栏的槽，避免两层 overflow 裁掉焦点环
      className="flex items-center gap-1"
    >
      {TAB_OPTIONS.map(({ value, label, icon: Icon }) => {
        const active = value === tab
        return (
          <button
            key={value}
            type="button"
            role="tab"
            id={panelId ? `${panelId}-tab-${value}` : undefined}
            aria-selected={active}
            aria-controls={panelId}
            tabIndex={active ? 0 : -1}
            onClick={() => onTabChange(value)}
            className={cn(
              "flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm sm:px-3 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring",
              active ? "bg-brand/10 font-medium text-brand" : "text-muted-foreground hover:bg-brand/5 hover:text-brand",
            )}
          >
            <Icon className="hidden size-4 shrink-0 sm:block" aria-hidden />
            <span className="whitespace-nowrap">{label}</span>
          </button>
        )
      })}
    </div>
  )
}
