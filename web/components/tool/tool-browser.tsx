"use client"

import {
  Suspense,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react"
import { useSearchParams } from "next/navigation"
import type { Topic, Tool, ToolIndex } from "@/lib/types"
import { decodeToolIndex, MAX_TOOL_PAGE_SIZE, sortToolIndex, TOOL_PAGE_SIZE, type ToolIndexPayload } from "@/lib/tool"
import {
  getSort,
  getTab,
  getView,
  setSort as persistSort,
  setView as persistView,
  subscribePreferences,
} from "@/lib/preferences"
import { ToolRow } from "@/components/tool/tool-row"
import { ToolCard } from "@/components/tool/tool-card"
import { ToolToolbar } from "@/components/tool/toolbar"
import { Button } from "@/components/ui/button"
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import {
  readUrlParams,
  resolveInitialTab,
  type SortMode,
  type TabMode,
  type UrlState,
  type ViewMode,
} from "@/lib/tool-query"
import { useMounted } from "@/hooks/use-mounted"
import { formatCount } from "@/lib/format"
import { PackageOpen } from "lucide-react"
import { Skeleton } from "@/components/ui/skeleton"
import Link from "next/link"

interface ToolBrowserProps {
  /**
   * 轻量索引：只含排序/筛选需要的字段。
   * 页面默认不再传（HTML 会少约 470 KB），由组件在 hydration 后拉 `/api/index`。
   * 测试/Storybook 仍可直接注入以获得确定性。
   */
  index?: readonly ToolIndex[]
  /** 当前范围（主题页传 topic id），用于只拉该主题的索引。 */
  topic?: string
  /** 首屏已由 server 渲染好的完整工具（默认推荐序前 N 条）。 */
  initialTools: readonly Tool[]
  /** 每页条数，默认 60。 */
  pageSize?: number
  emptyTitle?: string
  emptyDescription?: string
  defaultView?: ViewMode
  defaultSort?: SortMode
  showTabs?: boolean
  defaultTab?: TabMode
  /** 无 tabs 页面（主题页）工具栏左侧的自定义内容，如主题图标 + 名称。 */
  title?: ReactNode
  /** 主题真源（id → 名称/图标），用于卡片/列表展示主题。缺省则只显示域名。 */
  topics?: readonly Topic[]
}

/**
 * 订阅 URL 查询（含同路由软导航，如首页「探索精选」→ /?tab=featured）并同步进组件状态。
 * useSearchParams 需在 Suspense 边界内；该子组件不渲染内容，故不影响页面 SSR。
 */
function UrlStateSync({ onChange }: { onChange: (state: UrlState) => void }) {
  const searchParams = useSearchParams()
  const search = searchParams.toString()

  useEffect(() => {
    onChange(readUrlParams(search))
  }, [search, onChange])

  return null
}

const noopSubscribe = () => () => {}
const emptyString = ""

/** SSR 期退化为 useEffect，客户端用 useLayoutEffect 在首绘帧前揭示（避免中介帧闪烁）。 */
const useIsomorphicLayoutEffect = typeof window !== "undefined" ? useLayoutEffect : useEffect

function getUrlSearch(): string {
  if (typeof window === "undefined") return emptyString
  return window.location.search
}

export function ToolBrowser({
  index,
  topic,
  initialTools,
  pageSize = TOOL_PAGE_SIZE,
  emptyTitle,
  emptyDescription,
  defaultView = "grid",
  defaultSort = "recommended",
  showTabs = true,
  defaultTab = "all",
  title,
  topics,
}: ToolBrowserProps) {
  // 每实例唯一前缀：避免同页多实例（或 SSR/客户端）产生重复 DOM id 与错位的 aria 关联
  const uid = useId()
  const panelId = `${uid}-panel`

  const storedViewRaw = useSyncExternalStore(subscribePreferences, getView, () => null)
  const storedSortRaw = useSyncExternalStore(subscribePreferences, getSort, () => null)
  const storedTabRaw = useSyncExternalStore(subscribePreferences, getTab, () => null)
  const urlSearch = useSyncExternalStore(noopSubscribe, getUrlSearch, () => emptyString)
  const mounted = useMounted()

  // 挂载前一律忽略本地偏好：SSG 服务端读不到 localStorage，若客户端首次渲染就用偏好值
  // 会导致排序/视图与 SSR 不一致（hydration mismatch）。故挂载后才应用。
  const storedView = mounted ? storedViewRaw : null
  const storedSort = mounted ? storedSortRaw : null
  const storedTab = mounted ? storedTabRaw : null

  const initial = useMemo(() => readUrlParams(mounted ? urlSearch : ""), [urlSearch, mounted])
  const initialView = initial.view ?? storedView ?? defaultView
  const initialSort = initial.sort ?? storedSort ?? defaultSort
  // 默认 Tab 仅在展示 Tab 的页面生效：否则（如主题页）会静默过滤工具却无切换入口
  const initialTab = resolveInitialTab({ urlTab: initial.tab, storedTab, defaultTab, showTabs })

  const [viewOverride, setViewOverride] = useState<ViewMode | null>(null)
  const [sortOverride, setSortOverride] = useState<SortMode | null>(null)
  const [tabOverride, setTabOverride] = useState<TabMode | null>(null)

  const view = viewOverride ?? initialView
  const sort = sortOverride ?? initialSort
  const tab = tabOverride ?? initialTab

  // PB-01：首帧由 prefsScript 隐藏工具区（仅当偏好≠默认），hydration 应用真实偏好后揭示。
  // mounted 与 stored* 同由 useSyncExternalStore 驱动，同一次重渲染翻转，故揭示时偏好已就绪。
  useIsomorphicLayoutEffect(() => {
    if (!mounted) return
    document.documentElement.removeAttribute("data-prefs")
  }, [mounted, view, sort, tab])

  const applyUrlState = useCallback((state: UrlState) => {
    setTabOverride(state.tab)
    setViewOverride(state.view)
    setSortOverride(state.sort)
  }, [])

  // tab/view/sort 在 URL 上保持一致：仅在值与「当前 URL」不同时重写，避免与传入的
  // 链接参数（如 Hero 的 ?tab=all#tool-browser）互相覆盖。
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const hadTab = params.has("tab")
    params.delete("filter") // 旧版别名，统一由 tab 表达
    // tab：值为默认值时通常不写入 URL；但若 URL 本就显式带 tab（如 ?tab=all），保留以示选中
    if (showTabs && (tab !== defaultTab || hadTab)) params.set("tab", tab)
    else params.delete("tab")
    if (view !== defaultView) params.set("view", view)
    else params.delete("view")
    if (sort !== defaultSort) params.set("sort", sort)
    else params.delete("sort")

    const qs = params.toString()
    const next = qs ? `${window.location.pathname}?${qs}` : window.location.pathname
    const current = `${window.location.pathname}${window.location.search}`
    if (next !== current) window.history.replaceState(null, "", `${next}${window.location.hash}`)
  }, [tab, view, sort, defaultTab, defaultView, defaultSort, showTabs])

  const resolvedSort: SortMode = sort

  const setView = (v: ViewMode) => {
    persistView(v)
    setViewOverride(v)
  }

  const setSort = (s: SortMode) => {
    persistSort(s)
    setSortOverride(s)
  }

  // 切换 tab 不写入默认偏好：Tab 为会话级筛选（体现在 URL），「默认 Tab」仅在设置页修改
  const setTab = (t: TabMode) => {
    setTabOverride(t)
  }

  // 索引外置：没有注入时在 hydration 后拉取；首屏先用 initialTools 渲染，避免空白/骨架。
  const [lazyIndex, setLazyIndex] = useState<readonly ToolIndex[] | null>(null)
  const [indexError, setIndexError] = useState(false)
  const [indexRetry, setIndexRetry] = useState(0)

  useEffect(() => {
    if (index) return
    const controller = new AbortController()
    fetch(`/api/index${topic ? `?topic=${encodeURIComponent(topic)}` : ""}`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return response.json() as Promise<ToolIndexPayload | ToolIndex[]>
      })
      .then((payload) => {
        setLazyIndex(decodeToolIndex(payload))
        setIndexError(false)
      })
      .catch(() => {
        if (!controller.signal.aborted) setIndexError(true)
      })
    return () => controller.abort()
  }, [index, indexRetry, topic])

  const effectiveIndex = index ?? lazyIndex
  const indexReady = effectiveIndex !== null

  const [details, setDetails] = useState<Map<string, Tool>>(() => new Map(initialTools.map((tool) => [tool.id, tool])))
  /** 已加载条数与列表键绑定：切 tab/排序自动回到第一批，不需要额外的 reset effect。 */
  const [visibleState, setVisibleState] = useState(() => ({ key: "", count: 0 }))
  const sentinelRef = useRef<HTMLDivElement>(null)
  const [retryToken, setRetryToken] = useState(0)
  const [errorKey, setErrorKey] = useState("")
  const [unavailableIds, setUnavailableIds] = useState<ReadonlySet<string>>(() => new Set())

  // 首屏由 server 直接给出；后续 sort/tab 变化或增量加载时，把新拿到的完整工具并入（纯派生，无 effect）。
  const mergedDetails = useMemo(() => {
    if (initialTools.every((tool) => details.has(tool.id))) return details
    const next = new Map(details)
    for (const tool of initialTools) next.set(tool.id, tool)
    return next
  }, [details, initialTools])

  const perPage = Math.min(MAX_TOOL_PAGE_SIZE, Math.max(1, pageSize))
  const listKey = `${tab}|${resolvedSort}`

  // 旧部署留下的 index 可能包含已被下架的工具；API 返回数量对不上时把它们从列表剔除，
  // 否则 missingKey 永远不变、列表会卡在骨架里。
  const availableIndex = useMemo(
    () => (effectiveIndex ?? []).filter((tool) => !unavailableIds.has(tool.id)),
    [effectiveIndex, unavailableIds],
  )

  const filtered = useMemo(() => {
    if (!indexReady) return []
    const list = tab === "featured" ? availableIndex.filter((tool) => tool.featured) : availableIndex
    return sortToolIndex(list, resolvedSort)
  }, [availableIndex, indexReady, tab, resolvedSort])

  const visibleCount = visibleState.key === listKey ? visibleState.count : perPage
  const visible = useMemo(
    () => (indexReady ? filtered.slice(0, visibleCount) : []),
    [filtered, indexReady, visibleCount],
  )
  const missingKey = useMemo(
    () =>
      visible
        .filter((tool) => !mergedDetails.has(tool.id))
        .map((tool) => tool.id)
        .join(","),
    [visible, mergedDetails],
  )
  const hasMissing = indexReady && missingKey.length > 0
  const fetchKey = hasMissing ? `${missingKey}|${retryToken}` : ""
  const loadError = hasMissing && errorKey === fetchKey

  // 只取当前页缺失的完整字段；排序/筛选仍由轻量索引在客户端完成，交互不退化。
  // 错误态由 fetchKey 派生，effect 内不直接 setState，避免级联渲染。
  useEffect(() => {
    if (!missingKey) return
    const controller = new AbortController()
    let cancelled = false
    fetch(`/api/tools?ids=${encodeURIComponent(missingKey)}`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return response.json() as Promise<Tool[]>
      })
      .then((items) => {
        if (cancelled) return
        setDetails((prev) => {
          const next = new Map(prev)
          for (const tool of items) next.set(tool.id, tool)
          return next
        })
        const returned = new Set(items.map((tool) => tool.id))
        const missing = missingKey.split(",").filter((id) => id && !returned.has(id))
        if (missing.length > 0) {
          setUnavailableIds((prev) => {
            const next = new Set(prev)
            for (const id of missing) next.add(id)
            return next
          })
        }
      })
      .catch((error: unknown) => {
        if (cancelled || (error instanceof DOMException && error.name === "AbortError")) return
        setErrorKey(fetchKey)
      })
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [fetchKey, missingKey])

  const visibleTools = useMemo(() => {
    // 索引还没到时先展示 server 给的第一页；索引到达后切到正常的排序/分页派生。
    if (!indexReady) return initialTools.slice(0, perPage)
    return visible.map((tool) => mergedDetails.get(tool.id)).filter((tool): tool is Tool => Boolean(tool))
  }, [indexReady, initialTools, mergedDetails, perPage, visible])

  // 主题 id→名称/图标 查找表（O(1)/次）；缺 topics 时返回空
  const topicMap = useMemo(() => new Map((topics ?? []).map((c) => [c.id, c])), [topics])
  /** 滚动到接近哨兵时追加一批；IntersectionObserver 不可用时保留首屏，不阻塞页面。 */
  useEffect(() => {
    if (!indexReady || hasMissing) return
    const node = sentinelRef.current
    if (!node || typeof IntersectionObserver === "undefined") return
    if (visibleCount >= filtered.length) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return
        setVisibleState((previous) => {
          const current = previous.key === listKey ? previous.count : perPage
          return { key: listKey, count: Math.min(current + perPage, filtered.length) }
        })
      },
      // 提前 600px 触发：滚到底之前就开始取下一批，避免出现“空白等待”
      { rootMargin: "600px 0px" },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [filtered.length, hasMissing, indexReady, listKey, perPage, visibleCount])

  const topicOf = useCallback(
    (tool: Tool) => {
      const id = tool.topics[0]
      const cat = id ? topicMap.get(id) : undefined
      return { label: cat?.name ?? "", icon: cat?.icon }
    },
    [topicMap],
  )

  // 已有完整工具时保留列表，只在尾部挂加载/错误提示；只有一条都没有时才用整块骨架。
  const renderBrowserContent = () => {
    if (visibleTools.length === 0) {
      return loadError ? (
        <ToolListError onRetry={() => setRetryToken((token) => token + 1)} />
      ) : (
        <ToolListSkeleton view={view} count={Math.min(Math.max(visible.length, 1), 12)} />
      )
    }
    return (
      <>
        <BrowserContent view={view} tools={visibleTools} topicOf={topicOf} />
        {hasMissing &&
          (loadError ? (
            <div className="pt-3">
              <ToolListError onRetry={() => setRetryToken((token) => token + 1)} />
            </div>
          ) : (
            <div className="pt-3">
              <ToolListSkeleton view={view} count={3} />
            </div>
          ))}
      </>
    )
  }

  return (
    <div id="tool-browser" className="scroll-mt-28 md:scroll-mt-8">
      <Suspense fallback={null}>
        <UrlStateSync onChange={applyUrlState} />
      </Suspense>
      <div className="flex flex-col gap-4">
        {indexError && !indexReady && (
          <div
            role="status"
            className="flex items-center justify-between gap-3 rounded-lg border border-dashed px-3 py-2 text-xs text-muted-foreground"
          >
            <span>索引加载失败，排序与翻页暂不可用。</span>
            <Button variant="outline" size="sm" onClick={() => setIndexRetry((token) => token + 1)}>
              重试
            </Button>
          </div>
        )}
        {/* 空结果时仍展示工具栏，保住主题图标/名称等页面身份信息 */}
        <ToolToolbar
          view={view}
          tab={tab}
          sort={sort}
          showTabs={showTabs}
          panelId={panelId}
          title={title}
          onViewChange={setView}
          onTabChange={setTab}
          onSortChange={setSort}
        />

        {indexReady && filtered.length === 0 ? (
          <Empty className="py-12">
            <EmptyMedia variant="icon">
              <PackageOpen />
            </EmptyMedia>
            <EmptyHeader>
              <EmptyTitle>{emptyTitle ?? "暂无工具"}</EmptyTitle>
              {emptyDescription && <EmptyDescription>{emptyDescription}</EmptyDescription>}
            </EmptyHeader>
            <EmptyContent>
              <Button variant="outline" render={<Link href="/" />}>
                浏览全部工具
              </Button>
            </EmptyContent>
          </Empty>
        ) : (
          <>
            {showTabs ? (
              <div
                role="tabpanel"
                id={panelId}
                aria-labelledby={panelId ? `${panelId}-tab-${tab}` : undefined}
                aria-label={panelId ? undefined : "工具列表"}
              >
                {renderBrowserContent()}
              </div>
            ) : (
              renderBrowserContent()
            )}
            {indexReady && filtered.length > perPage && (
              <div
                ref={sentinelRef}
                aria-live="polite"
                className="flex flex-col items-center gap-2 border-t border-border pt-4 text-xs text-muted-foreground"
              >
                {visible.length < filtered.length ? (
                  hasMissing ? (
                    <>
                      <span
                        className="size-5 animate-spin rounded-full border-2 border-border border-t-foreground/70"
                        aria-hidden
                      />
                      <span>加载中…</span>
                    </>
                  ) : (
                    <span>
                      已显示 {formatCount(visible.length)} / {formatCount(filtered.length)}，继续向下滚动
                    </span>
                  )
                ) : (
                  <span>已显示全部 {formatCount(filtered.length)} 个工具</span>
                )}
              </div>
            )}{" "}
          </>
        )}
      </div>
    </div>
  )
}

function ToolListError({ onRetry }: { onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center gap-3 rounded-lg border border-dashed py-10 text-sm text-muted-foreground"
    >
      <span>加载失败，请检查网络后重试。</span>
      <Button variant="outline" onClick={onRetry}>
        重试
      </Button>
    </div>
  )
}

function ToolListSkeleton({ view, count }: { view: ViewMode; count: number }) {
  const items = Array.from({ length: Math.max(1, count) })
  if (view === "list") {
    return (
      <div role="status" aria-label="加载中" aria-busy="true" className="overflow-hidden rounded-lg border bg-card">
        {items.map((_, index) => (
          <div key={index} className="flex items-center gap-3 border-b border-border px-4 py-3.5 last:border-b-0">
            <div className="min-w-0 flex-1">
              <Skeleton className="h-5 w-40 max-w-full" />
              <Skeleton className="mt-2 h-4 w-3/4 max-w-full" />
            </div>
            <Skeleton className="h-5 w-16" />
          </div>
        ))}
      </div>
    )
  }
  return (
    <div role="status" aria-label="加载中" aria-busy="true" className="tool-card-grid">
      {items.map((_, index) => (
        <div key={index} className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
          <Skeleton className="h-5 w-2/3" />
          <div className="flex flex-col gap-1.5">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
          </div>
          <div className="flex gap-1">
            <Skeleton className="h-5 w-16" />
            <Skeleton className="h-5 w-12" />
          </div>
          <div className="mt-auto flex items-center justify-between">
            <Skeleton className="h-5 w-14" />
            <Skeleton className="h-4 w-24" />
          </div>
        </div>
      ))}
    </div>
  )
}

function BrowserContent({
  view,
  tools,
  topicOf,
}: {
  view: ViewMode
  tools: readonly Tool[]
  topicOf: (tool: Tool) => { label: string; icon?: string }
}) {
  if (view === "grid") {
    return (
      <div className="tool-card-grid">
        {tools.map((tool) => {
          const c = topicOf(tool)
          return <ToolCard key={tool.id} tool={tool} topicLabel={c.label} topicIcon={c.icon} />
        })}
      </div>
    )
  }
  return (
    <div className="rounded-lg border bg-card">
      {tools.map((tool, i) => {
        const c = topicOf(tool)
        return (
          <ToolRow key={tool.id} tool={tool} last={i === tools.length - 1} topicLabel={c.label} topicIcon={c.icon} />
        )
      })}
    </div>
  )
}
