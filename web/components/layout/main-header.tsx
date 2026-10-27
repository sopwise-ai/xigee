"use client"

import { Suspense, useCallback, useEffect, useRef, useState, type RefObject } from "react"
import Link from "next/link"
import { Search, Settings, X } from "lucide-react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from "@/components/ui/input-group"
import { Kbd } from "@/components/ui/kbd"
import ThemeToggle from "@/components/layout/theme-toggle"
import { SearchSuggestions, suggestionOptionId } from "@/components/search/search-suggestions"
import { useDebouncedValue } from "@/hooks/use-debounced-value"
import { SEARCH_FOCUS_RESULTS_EVENT, SEARCH_RESULT_SELECTOR, type SuggestionDoc } from "@/lib/search"
import { MAX_SEARCH_QUERY_LENGTH } from "@/lib/search-limits"
import { searchPageHref, writeSearchQuery } from "@/lib/url"
import type { Topic } from "@/lib/types"

/** 「边打边搜」的防抖时长：吃掉连打，又短到感觉是即打即搜。 */
const SEARCH_DEBOUNCE_MS = 150

/**
 * 查询回填：隔离在 Suspense 内读取 useSearchParams，使输入框本身仍可 SSR（不随查询串退化为客户端渲染）；
 * 依赖 query 而非 pathname，覆盖「同路径仅查询串变化」（如点击推荐词）。
 *
 * **聚焦时不回填**：边打边搜模式下 URL 是跟着输入走的，此刻回填会把用户刚敲的字吃掉
 * （URL 由防抖写入，永远落后输入框一拍）。只有外部变更（后退/前进、点链接）才需要同步。
 */
function QuerySync({
  inputRef,
  onQueryChange,
}: {
  inputRef: RefObject<HTMLInputElement | null>
  onQueryChange: (value: string) => void
}) {
  const searchParams = useSearchParams()
  const query = searchParams.get("q") ?? ""

  useEffect(() => {
    const el = inputRef.current
    if (!el) {
      onQueryChange(query)
      return
    }
    if (document.activeElement === el) return
    if (el.value !== query) {
      el.value = query
      onQueryChange(query)
    }
  }, [inputRef, query, onQueryChange])

  return null
}

/**
 * 主区顶栏搜索框：全站按 `/` 聚焦（非输入态）。
 *
 * - **搜索页内边打边搜**：写 URL 走 `history.replaceState`，Next 打过补丁，只同步 Router
 *   不发请求 —— 结果同帧更新，换词不再有网络往返（旧版每次回车都要跑一趟服务器）。
 * - **其它页出建议下拉**：↑↓ 选择、回车进结果页，选中后回车直接打开工具。
 * - **`<form action="/search">` 兜底**：hydration 完成前（首屏 3 秒级）按回车走原生 GET
 *   提交跳到 `/search?q=…`，而不是像旧版那样毫无反应。
 */
function SearchField() {
  const inputRef = useRef<HTMLInputElement>(null)
  const rootRef = useRef<HTMLFormElement>(null)
  const router = useRouter()
  const pathname = usePathname()

  const [hasValue, setHasValue] = useState(false)
  /** 输入框当前内容的镜像：非受控输入（保持 SSR 稳定），用它驱动建议与防抖。 */
  const [draft, setDraft] = useState("")
  const [focused, setFocused] = useState(false)
  /** Esc 关掉过下拉后置位，避免「输入框还聚焦着」把下拉立刻又算出来。 */
  const [dismissed, setDismissed] = useState(false)
  /**
   * 键盘选中项，连同「它是哪一次输入选中的」一起存。
   * 查询一变 `activeIndex` 就在渲染期派生成 -1 —— 用派生代替「在 effect 里 setState」，
   * 少一次级联渲染，也不会让高亮残留在已经换掉的建议列表上。
   */
  const [active, setActive] = useState({ query: "", index: -1 })

  const isSearchPage = pathname === "/search"
  const deferred = useDebouncedValue(draft, SEARCH_DEBOUNCE_MS)
  const [suggestions, setSuggestions] = useState<{ query: string; items: readonly SuggestionDoc[] }>({
    query: "",
    items: [],
  })

  // 建议按查询串走 API：根布局不再下发 6000+ 条索引，首访每个页面都能少约 170KB(gzip)。
  // 用与「边打边搜」相同的防抖，既保留即时感，也避免每个按键都打一次 Fuse。
  useEffect(() => {
    if (isSearchPage || !focused || !deferred.trim()) return
    const controller = new AbortController()
    fetch(`/api/suggest?q=${encodeURIComponent(deferred)}`, { signal: controller.signal })
      .then((response) => (response.ok ? (response.json() as Promise<SuggestionDoc[]>) : []))
      .then((next) => setSuggestions({ query: deferred, items: next }))
      .catch(() => {
        /* 建议是增强功能：失败时按「无建议」处理，输入与提交不受影响 */
        if (!controller.signal.aborted) setSuggestions({ query: deferred, items: [] })
      })
    return () => controller.abort()
  }, [deferred, focused, isSearchPage])

  // 只展示与当前输入匹配的那一批，避免上一轮请求的结果短暂串台。
  const items = suggestions.query === draft ? suggestions.items : []

  const listboxId = "search-suggestions"
  const settled = suggestions.query === draft
  /**
   * 有响应才开：加载中不弹「正在搜索」空层，避免每个按键闪一下；
   * 响应为空时也要开，给「没有匹配建议 / 查看全部」的反馈，而不是静默无响应。
   * 搜索页不弹：结果已经在下方实时更新，再来一份下拉是重复信息。
   */
  const open = !isSearchPage && focused && !dismissed && draft.trim().length > 0 && (items.length > 0 || settled)
  const activeIndex = active.query === draft && active.index >= 0 && active.index < items.length ? active.index : -1

  const moveActive = (delta: number) => {
    const current = active.query === draft ? active.index : -1
    if (items.length === 0) {
      setActive({ query: draft, index: -1 })
      return
    }
    // 未选中时：↓ 落到第一条、↑ 落到最后一条；已选中则上下回绕
    const next = current < 0 ? (delta > 0 ? 0 : items.length - 1) : (current + delta + items.length) % items.length
    setActive({ query: draft, index: next })
  }
  const resetActive = () => setActive({ query: draft, index: -1 })

  const syncValueFlag = useCallback((value: string) => {
    setHasValue(value.length > 0)
    setDraft(value)
    // 输入内容一变就作废键盘选中，避免「删掉再打回来」时高亮指到意料之外的旧条目
    setActive({ query: value, index: -1 })
  }, [])

  // 防抖后的 URL 同步：只在搜索页原地写（零网络），其它页不动地址栏
  useEffect(() => {
    if (isSearchPage) writeSearchQuery(deferred, pathname, window.location.search)
  }, [deferred, isSearchPage, pathname])

  // 点击下拉之外的区域收起（含点建议本身：下方 onClick 里一并处理）
  useEffect(() => {
    if (!focused) return
    const onPointerDown = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) {
        setFocused(false)
        setDismissed(false)
      }
    }
    document.addEventListener("pointerdown", onPointerDown)
    return () => document.removeEventListener("pointerdown", onPointerDown)
  }, [focused])

  const prefetchedRef = useRef(false)
  /** 首次开始搜索时预取 /search：之后回车进结果页走客户端缓存，不再等一次 RSC 往返。 */
  const ensurePrefetched = useCallback(() => {
    if (prefetchedRef.current) return
    prefetchedRef.current = true
    router.prefetch("/search")
  }, [router])

  const isTypingTarget = (el: EventTarget | null) => {
    if (!(el instanceof HTMLElement)) return false
    const tag = el.tagName
    return tag === "INPUT" || tag === "TEXTAREA" || el.isContentEditable
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey) return
      if (isTypingTarget(e.target)) return
      e.preventDefault()
      inputRef.current?.focus()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  /** 提交搜索：搜索页原地定格 URL（不等防抖、不发请求），其它页才做一次客户端跳转。 */
  const submitSearch = () => {
    const trimmed = inputRef.current?.value.trim() ?? ""
    // 提交即收起：客户端跳转不会重挂主区顶栏，不显式关闭会把建议浮层带进结果页。
    setFocused(false)
    setDismissed(true)
    if (isSearchPage) {
      writeSearchQuery(trimmed, pathname, window.location.search)
      return
    }
    ensurePrefetched()
    router.push(searchPageHref(trimmed))
  }

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    submitSearch()
  }

  /** 清空输入并同步移除 URL 上的 q（保留其它查询参数），保留原有「清空并聚焦」语义。 */
  const handleClear = () => {
    const el = inputRef.current
    if (!el) return
    el.value = ""
    setDraft("")
    setHasValue(false)
    setDismissed(false)
    resetActive()
    const params = new URLSearchParams(window.location.search)
    if (params.has("q")) {
      params.delete("q")
      const qs = params.toString()
      window.history.replaceState(null, "", qs ? `${window.location.pathname}?${qs}` : window.location.pathname)
    }
    el.focus()
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") {
      // 下拉开着先收下拉（保留已输入内容），再清空，最后才失焦
      if (open) {
        setDismissed(true)
        resetActive()
        return
      }
      if (e.currentTarget.value) handleClear()
      else e.currentTarget.blur()
      return
    }

    if (open) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault()
        moveActive(e.key === "ArrowDown" ? 1 : -1)
        return
      }
      // 选中建议时回车 = 直接打开该工具；未选中则继续走表单提交（进结果页）
      if (e.key === "Enter" && activeIndex >= 0) {
        e.preventDefault()
        document.getElementById(suggestionOptionId(listboxId, activeIndex))?.click()
        resetActive()
        setFocused(false)
        setDismissed(false)
        return
      }
    }
    // 搜索页内按 ↓：把焦点交给结果列表（进入后由结果列表接管 ↑↓）
    if (isSearchPage && e.key === "ArrowDown" && document.querySelector(SEARCH_RESULT_SELECTOR)) {
      e.preventDefault()
      window.dispatchEvent(new Event(SEARCH_FOCUS_RESULTS_EVENT))
      return
    }
    // 其余情况交给 <form onSubmit>：Enter 与原生提交共用一条路径
  }

  const handleFormClick = (e: React.MouseEvent<HTMLFormElement>) => {
    // 点开建议（<a target="_blank">）后收起下拉；建议项的 data-history-* 埋点由 HistoryTracker 记录
    if ((e.target as HTMLElement).closest("a")) {
      setFocused(false)
      setDismissed(false)
    }
  }

  return (
    <form
      ref={rootRef}
      role="search"
      aria-label="站内搜索"
      action="/search"
      method="get"
      onSubmit={handleSubmit}
      onClick={handleFormClick}
      className="relative w-full max-w-sm"
    >
      <InputGroup className="group w-full">
        <Suspense fallback={null}>
          <QuerySync inputRef={inputRef} onQueryChange={syncValueFlag} />
        </Suspense>
        <InputGroupAddon>
          <Search className="text-muted-foreground/60 transition-colors group-focus-within/input-group:text-muted-foreground" />
        </InputGroupAddon>
        <InputGroupInput
          ref={inputRef}
          name="q"
          type="search"
          maxLength={MAX_SEARCH_QUERY_LENGTH}
          enterKeyHint="search"
          role="combobox"
          aria-label="搜索 AI 工具"
          aria-autocomplete="list"
          aria-expanded={open}
          // 收起时 listbox 并不在 DOM 里，此时不该声明 aria-controls（指向不存在的 id 是无效引用）
          aria-controls={open ? listboxId : undefined}
          aria-activedescendant={open && activeIndex >= 0 ? suggestionOptionId(listboxId, activeIndex) : undefined}
          autoComplete="off"
          onChange={(e) => {
            const value = e.currentTarget.value
            setHasValue(value.length > 0)
            setDraft(value)
            setActive({ query: value, index: -1 })
            setDismissed(false)
            setFocused(true)
            ensurePrefetched()
          }}
          onFocus={() => {
            setFocused(true)
            setDismissed(false)
            ensurePrefetched()
          }}
          onKeyDown={handleKeyDown}
          placeholder="搜索 AI 工具…"
        />
        <InputGroupAddon align="inline-end">
          {hasValue ? (
            <InputGroupButton
              size="icon-xs"
              aria-label="清除搜索"
              title="清除"
              className="text-muted-foreground hover:text-foreground"
              onClick={handleClear}
            >
              <X />
            </InputGroupButton>
          ) : (
            <Kbd aria-hidden>/</Kbd>
          )}
        </InputGroupAddon>
      </InputGroup>
      {open && (
        <SearchSuggestions
          items={items}
          query={draft}
          activeIndex={activeIndex}
          listboxId={listboxId}
          settled={settled}
          onViewAll={submitSearch}
        />
      )}
    </form>
  )
}

interface Crumb {
  label: string
  href?: string
}

function resolveCrumbs(pathname: string, topics: readonly Topic[]): Crumb[] {
  if (pathname.startsWith("/topic/")) {
    const id = pathname.slice("/topic/".length)
    const name = topics.find((c) => c.id === id)?.name
    return name ? [{ label: "全部工具", href: "/" }, { label: name }] : [{ label: "全部工具", href: "/" }]
  }
  if (pathname === "/") return [{ label: "全部工具" }]
  if (pathname === "/search") return [{ label: "搜索" }]
  if (pathname === "/history") return [{ label: "历史记录" }]
  if (pathname === "/settings") return [{ label: "设置" }]
  if (pathname === "/about") return [{ label: "关于" }]
  if (pathname === "/privacy") return [{ label: "隐私政策" }]
  if (pathname === "/terms") return [{ label: "服务条款" }]
  return [{ label: "页面未找到" }]
}

interface MainHeaderProps {
  className?: string
  topics: readonly Topic[]
}

/** 主区顶栏：左侧路由面包屑，右侧搜索 + 设置/主题入口。 */
export function MainHeader({ className, topics }: MainHeaderProps) {
  const pathname = usePathname()
  const crumbs = resolveCrumbs(pathname, topics)

  return (
    // 顶栏刻意通栏：面包屑贴主区左缘、搜索与右侧入口贴右缘，不跟居中的正文同宽。
    // 底色与分隔线本来就铺满主区，这里是让内容也横跨整条栏。
    // relative+z 只为让搜索建议下拉稳定压在正文之上，不改变任何度量。
    <header className={cn("relative z-40 h-14 shrink-0 border-b border-sidebar-border", className)}>
      <div className="flex h-full items-center gap-3 px-4 sm:px-6">
        <nav aria-label="面包屑" className="flex min-w-0 flex-1 items-center text-sm text-muted-foreground">
          <ol className="flex min-w-0 items-center">
            {crumbs.map((crumb, i) => {
              const isLast = i === crumbs.length - 1
              return (
                <li key={i} className="flex min-w-0 items-center">
                  {i > 0 && <span className="mx-1.5 text-muted-foreground/50">/</span>}
                  {isLast || !crumb.href ? (
                    <span aria-current={isLast ? "page" : undefined} className="truncate font-medium text-foreground">
                      {crumb.label}
                    </span>
                  ) : (
                    <Link href={crumb.href} className="truncate transition-colors hover:text-foreground">
                      {crumb.label}
                    </Link>
                  )}
                </li>
              )
            })}
          </ol>
        </nav>
        <SearchField />
        <Button variant="outline" size="icon" aria-label="设置" title="设置" render={<Link href="/settings" />}>
          <Settings />
        </Button>
        <ThemeToggle />
      </div>
    </header>
  )
}
