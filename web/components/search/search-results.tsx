"use client"

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react"
import Link from "next/link"
import { usePathname, useSearchParams } from "next/navigation"
import { Sparkles } from "lucide-react"
import { FilterSelect } from "@/components/ui/filter-select"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { SearchLanding } from "@/components/search/search-landing"
import { SearchNoResults } from "@/components/search/search-no-results"
import { SearchResultRow } from "@/components/search/search-result-row"
import { useDebouncedValue } from "@/hooks/use-debounced-value"
import { formatCount } from "@/lib/format"
import {
  addRecentSearch,
  clearRecentSearches,
  getRecentSearchesSnapshot,
  parseRecentSearches,
  subscribeRecentSearches,
} from "@/lib/recent-searches"
import { SEARCH_FOCUS_RESULTS_EVENT, SEARCH_RESULT_SELECTOR, type SearchDoc } from "@/lib/search"
import { readSearchState, SEARCH_SORT_OPTIONS, type SearchSort } from "@/lib/search-params"
import { writeSearchParams } from "@/lib/url"
import type { Topic, Tool } from "@/lib/types"

interface SearchResultsProps {
  featured: readonly Tool[]
  topics: readonly Topic[]
  topicCounts: Record<string, number>
}

interface SearchResponse {
  items: SearchDoc[]
  total: number
  hasMore: boolean
  related: SearchDoc[]
}

/** 每页结果数：搜索页只拿当前页，避免把 6000+ 条工具塞进 RSC payload。 */
const PAGE_SIZE = 50

/** 查询词静默多久算「一次搜索意图」，值得写进最近搜索。 */
const SETTLE_MS = 800

/** FNV-1a 32 位哈希：把查询串映射为洗牌种子。 */
function hashString(input: string): number {
  let h = 2166136261
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

/**
 * Fisher–Yates 洗牌（确定性：同一种子同结果）。
 * 种子取自查询串哈希，服务端与客户端一致 —— 无重排闪烁。
 */
function shuffleWithSeed<T>(items: readonly T[], seed: number): T[] {
  const arr = [...items]
  let s = seed || 1
  for (let i = arr.length - 1; i > 0; i--) {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0
    const j = Math.floor((s / 4294967296) * (i + 1))
    ;[arr[i], arr[j]] = [arr[j], arr[i]]
  }
  return arr
}

/**
 * 搜索结果：请求由 `/api/search` 服务端完成，客户端不再下载全量工具、也不再本地建 Fuse 索引。
 * 空查询仍走着陆态；无结果时用服务端返回的「也许相关」+ 精选推荐兜底。
 */
export function SearchResults({ featured, topics, topicCounts }: SearchResultsProps) {
  const searchParams = useSearchParams()
  const pathname = usePathname()
  const { query, sort } = readSearchState(searchParams)
  const trimmedQuery = query.trim()

  const [retryToken, setRetryToken] = useState(0)
  const requestKey = `${trimmedQuery}|${sort}|${retryToken}`
  const [result, setResult] = useState<{
    key: string
    query: string
    items: SearchDoc[]
    total: number
    related: SearchDoc[]
  }>({ key: "", query: "", items: [], total: 0, related: [] })
  const [errorKey, setErrorKey] = useState("")
  const [loadingMoreState, setLoadingMoreState] = useState<{ key: string; value: boolean }>({
    key: "",
    value: false,
  })
  const requestIdRef = useRef(0)
  const loadMoreControllerRef = useRef<AbortController | null>(null)

  const topicNames = useMemo(
    () => Object.fromEntries(topics.map((c) => [c.id, c.name])) as Record<string, string>,
    [topics],
  )

  const isStale = result.key !== requestKey
  const resultQuery = result.query
  const items = result.items
  const total = result.total
  const related = result.related
  const loading = Boolean(trimmedQuery) && isStale && errorKey !== requestKey
  const error = Boolean(trimmedQuery) && isStale && errorKey === requestKey
  const loadingMore = loadingMoreState.key === requestKey && loadingMoreState.value

  useEffect(() => {
    if (!trimmedQuery) return
    loadMoreControllerRef.current?.abort()

    const requestId = ++requestIdRef.current
    const controller = new AbortController()
    const key = requestKey
    const params = new URLSearchParams({
      q: trimmedQuery,
      sort,
      page: "1",
      pageSize: String(PAGE_SIZE),
    })

    fetch(`/api/search?${params.toString()}`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return response.json() as Promise<SearchResponse>
      })
      .then((data) => {
        if (requestId !== requestIdRef.current) return
        setResult({ key, query: trimmedQuery, items: data.items, total: data.total, related: data.related })
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return
        if (requestId !== requestIdRef.current) return
        setErrorKey(key)
        console.error("[search] 请求失败", reason)
      })

    return () => controller.abort()
  }, [requestKey, trimmedQuery, sort])

  useEffect(() => () => loadMoreControllerRef.current?.abort(), [])

  const loadMore = useCallback(() => {
    if (loadingMore || items.length >= total) return
    const key = requestKey
    const requestId = requestIdRef.current
    // 由已加载条数推导下一页，不依赖会跨 query 残留的 page state。
    const nextPage = Math.floor(items.length / PAGE_SIZE) + 1
    const controller = new AbortController()
    loadMoreControllerRef.current = controller
    const params = new URLSearchParams({
      q: trimmedQuery,
      sort,
      page: String(nextPage),
      pageSize: String(PAGE_SIZE),
    })

    setLoadingMoreState({ key, value: true })
    fetch(`/api/search?${params.toString()}`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return response.json() as Promise<SearchResponse>
      })
      .then((data) => {
        if (requestId !== requestIdRef.current) return
        setResult((prev) =>
          prev.key !== key ? prev : { ...prev, items: [...prev.items, ...data.items], total: data.total },
        )
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) console.error("[search] 加载更多失败", reason)
      })
      .finally(() => {
        setLoadingMoreState((prev) =>
          prev.key === key && loadMoreControllerRef.current === controller ? { key, value: false } : prev,
        )
      })
  }, [items.length, loadingMore, requestKey, sort, total, trimmedQuery])

  // 不同搜索词 → 不同推荐；同 URL 稳定。种子两端一致，故无重排闪烁。
  const displayedFeatured = useMemo(() => shuffleWithSeed(featured, hashString(trimmedQuery)), [featured, trimmedQuery])
  const suggestions = useMemo(() => displayedFeatured.slice(0, 5).map((p) => p.name), [displayedFeatured])

  // 最近搜索：只在客户端可得，服务端快照恒为空，hydration 后自然补上
  const recentRaw = useSyncExternalStore(subscribeRecentSearches, getRecentSearchesSnapshot, () => "[]")
  const recent = useMemo(() => parseRecentSearches(recentRaw), [recentRaw])

  // 查询词静默一段时间且确实有结果，才算一次值得记住的搜索 ——
  // 否则会把「c / cl / cla…」这些打字中间态灌满历史。
  const settledQuery = useDebouncedValue(trimmedQuery, SETTLE_MS)
  useEffect(() => {
    if (settledQuery && !isStale && total > 0) addRecentSearch(settledQuery)
  }, [settledQuery, isStale, total])

  const patch = useCallback(
    (next: Record<string, string | null>) => {
      writeSearchParams(pathname, window.location.search, next)
    },
    [pathname],
  )

  const handlePick = useCallback((next: string) => patch({ q: next }), [patch])
  const handleSortChange = useCallback(
    (next: SearchSort) => patch({ sort: next === "relevance" ? null : next }),
    [patch],
  )
  const handleClearRecent = useCallback(() => clearRecentSearches(), [])

  // 顶栏搜索框按 ↓ → 焦点进入第一条结果（两者无共同祖先，用全局事件解耦）
  useEffect(() => {
    const onFocusResults = () => document.querySelector<HTMLElement>(SEARCH_RESULT_SELECTOR)?.focus()
    window.addEventListener(SEARCH_FOCUS_RESULTS_EVENT, onFocusResults)
    return () => window.removeEventListener(SEARCH_FOCUS_RESULTS_EVENT, onFocusResults)
  }, [])

  /** 结果列表内 ↑↓ 在行之间移动焦点（行本身是可聚焦的 <a>）。 */
  const handleListKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return
    const rows = Array.from(e.currentTarget.querySelectorAll<HTMLElement>(SEARCH_RESULT_SELECTOR))
    const current = rows.indexOf(document.activeElement as HTMLElement)
    if (current === -1) return
    const next = e.key === "ArrowDown" ? Math.min(current + 1, rows.length - 1) : Math.max(current - 1, 0)
    if (next === current) return
    e.preventDefault()
    rows[next].focus()
  }

  if (!trimmedQuery) {
    return (
      <SearchLanding
        recent={recent}
        onClearRecent={handleClearRecent}
        suggestions={suggestions}
        topics={topics}
        topicCounts={topicCounts}
        onPick={handlePick}
      />
    )
  }

  if (loading && items.length === 0) {
    return (
      <div role="status" className="flex flex-col gap-3" aria-busy="true" aria-label="搜索中">
        <Skeleton className="h-5 w-52 rounded" />
        <div className="overflow-hidden rounded-lg border bg-card">
          {Array.from({ length: 6 }).map((_, index) => (
            <div key={index} className="border-b border-border px-4 py-3 last:border-b-0">
              <Skeleton className="h-4 w-1/4" />
              <Skeleton className="mt-2 h-4 w-3/4" />
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div
        role="alert"
        className="flex flex-col items-center gap-3 rounded-lg border border-dashed py-10 text-sm text-muted-foreground"
      >
        <span>搜索失败，请检查网络后重试。</span>
        <Button variant="outline" onClick={() => setRetryToken((token) => token + 1)}>
          重试
        </Button>
      </div>
    )
  }

  if (!error && total === 0) {
    return (
      <SearchNoResults
        query={trimmedQuery}
        fallback={related}
        featured={displayedFeatured}
        suggestions={suggestions}
        topics={topics}
        topicCounts={topicCounts}
        topicNames={topicNames}
        onPick={handlePick}
      />
    )
  }

  const currentSort = SEARCH_SORT_OPTIONS.find((o) => o.value === sort) ?? SEARCH_SORT_OPTIONS[0]

  return (
    <div className="flex flex-col gap-3" aria-busy={loading}>
      <div className="flex items-center justify-between gap-3">
        {/* 中文句子里的元素切分不要留空格：`{" "}` 或行内尾随空格会渲染成「个与 「对话」 相关」 */}
        <p role="status" aria-live="polite" className="min-w-0 flex-1 truncate text-sm text-muted-foreground">
          {loading ? (
            <>
              正在搜索<span className="font-medium text-foreground">「{trimmedQuery}」</span>…
            </>
          ) : (
            <>
              找到 <span className="font-data font-medium text-foreground">{formatCount(total)}</span> 个与
              <span className="font-medium text-foreground">「{trimmedQuery}」</span>相关的结果
            </>
          )}
        </p>
        <FilterSelect
          label="排序"
          icon={currentSort.icon}
          value={sort}
          options={SEARCH_SORT_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
          onChange={(value) => handleSortChange(value as SearchSort)}
          active={sort !== "relevance"}
        />
      </div>

      <div onKeyDown={handleListKeyDown} className="overflow-hidden rounded-lg border bg-card">
        {items.map((tool, i) => (
          <SearchResultRow
            key={tool.id}
            tool={tool}
            query={resultQuery}
            topicNames={topicNames}
            last={i === items.length - 1}
          />
        ))}
      </div>

      {!loading && items.length < total && (
        <div className="flex flex-col items-center gap-2 pt-1">
          <p className="font-data text-xs text-muted-foreground">
            已显示 {items.length} / {formatCount(total)}
          </p>
          <Button variant="outline" disabled={loadingMore} onClick={loadMore}>
            {loadingMore ? "加载中…" : `加载更多（剩余 ${formatCount(total - items.length)}）`}
          </Button>
        </div>
      )}

      <p className="flex items-center gap-1.5 pt-1 text-xs text-muted-foreground">
        <Sparkles className="size-3.5" aria-hidden />
        没有想要的？试试
        <Link href="/" className="text-foreground underline-offset-4 hover:underline">
          浏览全部工具
        </Link>
      </p>
    </div>
  )
}
