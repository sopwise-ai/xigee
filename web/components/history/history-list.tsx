"use client"

import { useCallback, useEffect, useMemo, useReducer, useState, useSyncExternalStore, useRef } from "react"
import Link from "next/link"
import { Clock, ListFilter, Search, Trash2, X } from "lucide-react"
import {
  clearHistory,
  filterHistory,
  getHistoryTopicIds,
  getHistorySnapshot,
  HISTORY_PERIODS,
  parseHistorySnapshot,
  removeFromHistory,
  subscribeHistory,
  type HistoryItem,
  type HistoryPeriod,
} from "@/lib/history"
import { formatCount } from "@/lib/format"
import { PageBar } from "@/components/layout/page-bar"
import { PricingBadge } from "@/components/tool/pricing-badge"
import { FilterSelect, type FilterOption } from "@/components/ui/filter-select"
import { useMounted } from "@/hooks/use-mounted"
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group"
import { Button } from "@/components/ui/button"
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import type { Topic } from "@/lib/types"

/** 分页步长：初始渲染 + 每次触底加载的条数（避免一次性渲染过多） */
const PAGE_SIZE = 40

/** 首帧骨架：历史数据仅在客户端（localStorage）可得，挂载前渲染同构骨架避免空态闪现（HG-01）。 */
function HistorySkeleton() {
  return (
    <div className="flex flex-col gap-3" aria-hidden>
      {/* 骨架同样走二级栏，保证挂载前后栏高与下边框位置不跳 */}
      <PageBar
        width="content"
        actions={
          <>
            <Skeleton className="h-4 w-14 rounded" />
            <Skeleton className="h-7 w-20 rounded-lg" />
          </>
        }
      >
        <Skeleton className="h-8 w-[85%] shrink-0 rounded-md sm:w-72" />
        <Skeleton className="h-8 w-24 rounded-lg" />
        <Skeleton className="h-8 w-24 rounded-lg" />
      </PageBar>
      <div className="overflow-hidden rounded-lg border bg-card">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="flex items-center gap-3 border-b border-border px-4 py-2.5 last:border-b-0">
            <div className="flex min-w-0 flex-1 flex-col gap-1.5">
              <Skeleton className="h-4 w-1/4 rounded" />
              <Skeleton className="h-3 w-1/2 rounded" />
            </div>
            <Skeleton className="size-8 shrink-0 rounded-md" />
          </div>
        ))}
      </div>
    </div>
  )
}

/** 相对时间：非法日期兜底，避免 "Invalid Date" 英文报错式文案（PG-13） */
function formatRelativeTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return "未知时间"
  const diff = Date.now() - date.getTime()
  const min = Math.floor(diff / 60000)
  if (min < 1) return "刚刚"
  if (min < 60) return `${min} 分钟前`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} 小时前`
  const day = Math.floor(hr / 24)
  if (day < 7) return `${day} 天前`
  return date.toLocaleDateString("zh-CN", { month: "short", day: "numeric" })
}

/** 一条历史行：名称 + 时间（右）；副行 域名 · 主题 · 次数；右侧删除。 */
function HistoryRow({ item, topicLabel, last }: { item: HistoryItem; topicLabel: string; last: boolean }) {
  const meta = [item.domain, topicLabel, item.visitCount > 1 ? `访问 ${formatCount(item.visitCount)} 次` : ""]
    .filter(Boolean)
    .join(" · ")
  const time = formatRelativeTime(item.lastVisitedAt)

  return (
    <li
      className={
        "group flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-secondary/40" +
        (last ? "" : " border-b border-border")
      }
    >
      <a
        href={item.url}
        target="_blank"
        rel="noopener noreferrer"
        data-history-id={item.id}
        data-history-name={item.name}
        data-history-url={item.url}
        data-history-topic={item.topicId}
        data-history-pricing={item.pricing ?? ""}
        className="flex min-w-0 flex-1 items-center gap-3 outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
      >
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{item.name}</p>
          <p className="truncate font-data text-xs text-muted-foreground">
            {meta}
            {/* 窄屏：时间并入副行，避免时间列隐藏后信息丢失 */}
            <span className="sm:hidden"> · {time}</span>
          </p>
        </div>
        {item.pricing ? (
          <span className="hidden shrink-0 sm:inline">
            <PricingBadge pricing={item.pricing} />
          </span>
        ) : null}
        <span className="hidden w-20 shrink-0 text-right font-data text-xs text-muted-foreground sm:inline">
          {time}
        </span>
      </a>
      <Button
        variant="ghost"
        size="icon"
        aria-label={`删除 ${item.name} 的历史记录`}
        title="删除"
        onClick={() => removeFromHistory(item.id)}
        className="shrink-0 text-muted-foreground/60 hover:bg-destructive/10 hover:text-destructive"
      >
        <Trash2 />
      </Button>
    </li>
  )
}

interface HistoryListProps {
  topics: readonly Topic[]
}

/** 历史记录列表：平铺（不分组）、搜索 + 主题/时间筛选、无限滚动分页、单条删除与清空。 */
export function HistoryList({ topics }: HistoryListProps) {
  // 相对时间每分钟刷新（PG-13）
  const [, forceTick] = useReducer((n: number) => n + 1, 0)
  useEffect(() => {
    const id = window.setInterval(forceTick, 60_000)
    return () => window.clearInterval(id)
  }, [])

  const mounted = useMounted()
  const raw = useSyncExternalStore(subscribeHistory, getHistorySnapshot, () => "[]")
  const [query, setQuery] = useState("")
  const [topicId, setTopicId] = useState("")
  const [period, setPeriod] = useState<HistoryPeriod>("all")
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)
  const [showClearConfirm, setShowClearConfirm] = useState(false)

  const topicName = useCallback((id: string) => topics.find((c) => c.id === id)?.name ?? "", [topics])

  const items = useMemo(() => parseHistorySnapshot(raw), [raw])

  // 筛选器可选项：主题按「全站主题顺序」排列（而非历史出现顺序），下拉更稳定
  const topicOptions = useMemo<FilterOption[]>(() => {
    const used = new Set(getHistoryTopicIds(items))
    const ordered = topics.filter((c) => used.has(c.id)).map((c) => ({ value: c.id, label: c.name }))
    // 兜底：历史中引用了已不存在于 topics 的 id，仍列出以免无法筛选
    for (const id of used) {
      if (!topics.some((c) => c.id === id)) ordered.push({ value: id, label: topicName(id) || id })
    }
    return [{ value: "", label: "全部主题" }, ...ordered]
  }, [items, topics, topicName])

  const periodOptions = useMemo<FilterOption[]>(
    () => HISTORY_PERIODS.map((p) => ({ value: p.value, label: p.label })),
    [],
  )

  // 搜索（名称/域名/主题）→ 主题 + 时间筛选
  const filtered = useMemo(() => {
    const base = filterHistory(items, { topicId, period })
    const q = query.trim().toLowerCase()
    if (!q) return base
    return base.filter((it) => {
      const name = (it.name ?? "").toLowerCase()
      const domain = (it.domain ?? "").toLowerCase()
      const cat = topicName(it.topicId).toLowerCase()
      return name.includes(q) || domain.includes(q) || cat.includes(q)
    })
  }, [items, query, topicId, period, topicName])

  // 触底加载更多（无限滚动）
  const sentinelRef = useRef<HTMLDivElement>(null)

  const visible = filtered.slice(0, visibleCount)
  const hasMore = visibleCount < filtered.length
  const isFiltered = query.trim() !== "" || topicId !== "" || period !== "all"

  useEffect(() => {
    const el = sentinelRef.current
    if (!el) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          setVisibleCount((n) => Math.min(n + PAGE_SIZE, filtered.length))
        }
      },
      { rootMargin: "200px" },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [filtered.length, query, topicId, period, hasMore])

  const resetVisible = () => setVisibleCount(PAGE_SIZE)
  const resetFilters = () => {
    setQuery("")
    setTopicId("")
    setPeriod("all")
    resetVisible()
  }

  if (!mounted) return <HistorySkeleton />

  if (items.length === 0) {
    return (
      <Empty role="status" className="rounded-lg border bg-card py-8">
        <EmptyMedia variant="icon" className="size-12 rounded-xl border [&_svg:not([class*='size-'])]:size-6">
          <Clock />
        </EmptyMedia>
        <EmptyHeader>
          <EmptyTitle>暂无访问记录</EmptyTitle>
          <EmptyDescription>浏览工具时自动记录，方便下次快速回到这里</EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button variant="outline" render={<Link href="/" />}>
            去逛逛
          </Button>
        </EmptyContent>
      </Empty>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      {/* 二级栏：左 搜索 + 主题/时间筛选；右 计数 + 清除筛选 + 清空 */}
      <PageBar
        width="content"
        actions={
          <>
            <span role="status" aria-live="polite" className="font-data text-xs text-muted-foreground">
              {isFiltered
                ? `${formatCount(filtered.length)} / ${formatCount(items.length)} 条`
                : `共 ${formatCount(items.length)} 条`}
            </span>
            {isFiltered && (
              <Button variant="ghost" size="sm" onClick={resetFilters}>
                <X data-icon="inline-start" aria-hidden />
                清除筛选
              </Button>
            )}
            <Button variant="destructive" size="sm" onClick={() => setShowClearConfirm(true)}>
              <Trash2 data-icon="inline-start" aria-hidden />
              清空全部
            </Button>
          </>
        }
      >
        <InputGroup className="w-[85%] shrink-0 sm:w-72">
          <InputGroupAddon>
            <Search className="text-muted-foreground/60" />
          </InputGroupAddon>
          <InputGroupInput
            type="search"
            enterKeyHint="search"
            aria-label="搜索历史记录"
            autoComplete="off"
            placeholder="搜索历史记录…"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              resetVisible()
            }}
          />
        </InputGroup>

        <FilterSelect
          label="按主题筛选"
          icon={ListFilter}
          value={topicId}
          options={topicOptions}
          onChange={(v) => {
            setTopicId(v)
            resetVisible()
          }}
          active={topicId !== ""}
        />
        <FilterSelect
          label="按时间筛选"
          icon={Clock}
          value={period}
          options={periodOptions}
          onChange={(v) => {
            setPeriod(v as HistoryPeriod)
            resetVisible()
          }}
          active={period !== "all"}
        />
      </PageBar>

      <AlertDialog open={showClearConfirm} onOpenChange={setShowClearConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认清空所有历史记录？</AlertDialogTitle>
            <AlertDialogDescription>此操作不可恢复，共 {items.length} 条记录</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                clearHistory()
              }}
            >
              确定清空
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* 筛选/搜索无结果：与"暂无记录"共用同一套 Empty 语言（虚线框区分于有数据态） */}
      {filtered.length === 0 ? (
        <Empty className="rounded-lg border border-dashed py-8">
          <EmptyMedia variant="icon">
            <Search />
          </EmptyMedia>
          <EmptyHeader>
            <EmptyTitle>{query.trim() ? `未找到与「${query.trim()}」匹配的记录` : "当前筛选条件下没有记录"}</EmptyTitle>
          </EmptyHeader>
          <EmptyContent>
            <Button variant="outline" size="sm" onClick={resetFilters}>
              <X data-icon="inline-start" aria-hidden />
              清除筛选
            </Button>
          </EmptyContent>
        </Empty>
      ) : (
        <>
          <ul className="overflow-hidden rounded-lg border bg-card">
            {visible.map((item, i) => (
              <HistoryRow
                key={item.id}
                item={item}
                topicLabel={item.topicId ? topicName(item.topicId) : ""}
                last={i === visible.length - 1 && !hasMore}
              />
            ))}
          </ul>

          {hasMore && (
            <div ref={sentinelRef} className="flex items-center justify-center py-2">
              <span className="font-data text-xs text-muted-foreground/80">
                已加载 {formatCount(visible.length)} / {formatCount(filtered.length)} · 滚动加载更多
              </span>
            </div>
          )}
        </>
      )}
    </div>
  )
}
