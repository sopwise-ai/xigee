"use client"

import { useEffect } from "react"
import { Kbd, KbdGroup } from "@/components/ui/kbd"
import { Highlighted } from "@/components/search/highlight"
import { toolHistoryAttrs } from "@/lib/tool"
import type { SuggestionDoc } from "@/lib/search"
import { getDomain } from "@/lib/url"
import { cn } from "@/lib/utils"

/** 每条建议的 DOM id：输入框用 `aria-activedescendant` 指向它，键盘选中即视觉选中。 */
export function suggestionOptionId(listboxId: string, index: number): string {
  return `${listboxId}-${index}`
}

interface SearchSuggestionsProps {
  items: readonly SuggestionDoc[]
  query: string
  activeIndex: number
  listboxId: string
  /** 当前输入是否已拿到响应；false 时显示「正在搜索建议」。 */
  settled?: boolean
  /** 点「查看全部结果」或按 Enter 时调用。 */
  onViewAll?: () => void
  className?: string
}

/**
 * 顶栏搜索建议下拉：纯展示组件（开合、键盘、数据都在 `SearchField` 里），
 * 因此可以直接单测渲染结果，不必先跑通输入逻辑。
 *
 * 结构遵循 combobox 模式：`role="listbox"` + `role="option"` + `aria-selected`，
 * 由输入框的 `aria-activedescendant` 关联高亮项，焦点始终留在输入框。
 *
 * **`id` / `role="option"` 必须挂在 `<a>` 上，不能挂在包一层的 `<li>` 上**：
 * `SearchField` 用 `getElementById(activeId).click()` 触发「回车打开」，
 * 而点击 `<li>` 不会激活它内部的链接 —— 挂错位置会让回车静默失效。
 * 同理 listbox 用 `<div>` 而不是 `<ul>`，让 option 成为它的直接子元素。
 */
export function SearchSuggestions({
  items,
  query,
  activeIndex,
  listboxId,
  settled = true,
  onViewAll,
  className,
}: SearchSuggestionsProps) {
  // 选中项滚进可视区：条数少，直接查 DOM 即可，不必为它再挂一层 ref 列表
  useEffect(() => {
    if (activeIndex < 0) return
    document.getElementById(suggestionOptionId(listboxId, activeIndex))?.scrollIntoView({ block: "nearest" })
  }, [activeIndex, listboxId])

  const empty = items.length === 0

  return (
    <div
      className={cn(
        "absolute left-0 right-0 top-[calc(100%+4px)] z-50 overflow-hidden rounded-lg border bg-popover text-popover-foreground shadow-lg",
        className,
      )}
    >
      <div id={listboxId} role="listbox" aria-label="搜索建议" className="max-h-72 overflow-y-auto p-1">
        {empty ? (
          <p role="status" className="px-2 py-3 text-sm text-muted-foreground">
            {settled ? (
              <>
                没有匹配建议，按 <Kbd>Enter</Kbd> 直接搜索「{query}」
              </>
            ) : (
              <>正在搜索建议…</>
            )}
          </p>
        ) : (
          items.map((item, i) => {
            const active = i === activeIndex
            const topic = item.topicNames[0]
            return (
              <a
                key={item.id}
                id={suggestionOptionId(listboxId, i)}
                role="option"
                aria-selected={active}
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                // 建议是「预览」，回车的默认动作仍是进结果页；选中后回车由 SearchField 触发 click
                tabIndex={-1}
                {...toolHistoryAttrs(item)}
                className={cn(
                  "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm outline-none",
                  active ? "bg-accent text-accent-foreground" : "hover:bg-accent/60",
                )}
              >
                <span className="min-w-0 flex-1 truncate font-medium">
                  <Highlighted text={item.name} query={query} variant="tint" />
                </span>
                {topic && <span className="shrink-0 text-xs text-muted-foreground">{topic}</span>}
                <span className="shrink-0 font-data text-xs text-muted-foreground">{getDomain(item.url)}</span>
              </a>
            )
          })
        )}
      </div>
      <div className="flex items-center justify-between border-t border-border px-2.5 py-1.5 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <KbdGroup>
            <Kbd>↑</Kbd>
            <Kbd>↓</Kbd>
          </KbdGroup>
          选择
        </span>
        <span className="flex items-center gap-2">
          {activeIndex >= 0 && (
            <span className="flex items-center gap-1">
              <Kbd>⏎</Kbd>
              打开
            </span>
          )}
          <button
            type="button"
            onClick={onViewAll}
            className="rounded px-1 py-0.5 underline-offset-4 outline-none hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring"
          >
            查看全部结果
          </button>
        </span>
      </div>
    </div>
  )
}
