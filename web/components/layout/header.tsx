"use client"

import { useEffect, useRef, useState } from "react"
import Link from "next/link"
import { Search, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from "@/components/ui/input-group"
import { usePathname, useRouter } from "next/navigation"
import { cn } from "@/lib/utils"
import { pageShell } from "@/lib/layout"
import { useDebouncedValue } from "@/hooks/use-debounced-value"
import { MAX_SEARCH_QUERY_LENGTH } from "@/lib/search-limits"
import { searchPageHref, writeSearchQuery } from "@/lib/url"
import ThemeToggle from "./theme-toggle"
import { MobileMenu } from "./mobile-menu"
import type { Topic } from "@/lib/types"
import { Wordmark } from "@/components/brand/wordmark"

/** 与主区顶栏 SearchField 同一个防抖时长，两端「边打边搜」手感一致。 */
const SEARCH_DEBOUNCE_MS = 150

/** 读取初始查询：仅在用户展开搜索框（客户端）时调用，避免 useSearchParams 使整条 header 退化为客户端渲染 */
function initialQuery(): string {
  if (typeof window === "undefined") return ""
  return new URLSearchParams(window.location.search).get("q") ?? ""
}

/**
 * 移动端搜索：展开后为受控输入框，失焦或按 Esc 收起（无独立关闭按钮，节省窄屏空间）。
 * 有内容时按 Esc 先清空，再次 Esc 才收起——与常见命令栏一致。
 *
 * 在搜索页内边打边搜（`replaceState`，零网络往返）；其余页面回车才跳转。
 * 外层 `<form action="/search">` 保证 hydration 完成前回车仍走原生 GET 提交。
 */
function MobileSearchInput({ onClose, onCancel }: { onClose: () => void; onCancel: () => void }) {
  const [value, setValue] = useState(initialQuery)
  const router = useRouter()
  const pathname = usePathname()
  const isSearchPage = pathname === "/search"
  const deferred = useDebouncedValue(value, SEARCH_DEBOUNCE_MS)

  useEffect(() => {
    if (isSearchPage) writeSearchQuery(deferred, pathname, window.location.search)
  }, [deferred, isSearchPage, pathname])

  const handleSearch = () => {
    const trimmed = value.trim()
    if (isSearchPage) {
      writeSearchQuery(trimmed, pathname, window.location.search)
      return
    }
    router.push(searchPageHref(trimmed))
    onClose()
  }

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    handleSearch()
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    // Enter 交给 <form onSubmit>：键盘提交与原生 GET 提交同一条路径，不重复触发
    if (e.key === "Escape") {
      if (value) setValue("")
      else onCancel()
    }
  }

  return (
    <form role="search" aria-label="站内搜索" action="/search" method="get" onSubmit={handleSubmit} className="w-full">
      <InputGroup className="w-full">
        <InputGroupAddon>
          <Search className="text-muted-foreground/60" />
        </InputGroupAddon>
        <InputGroupInput
          autoFocus
          name="q"
          type="search"
          maxLength={MAX_SEARCH_QUERY_LENGTH}
          enterKeyHint="search"
          aria-label="搜索 AI 工具"
          autoComplete="off"
          placeholder="搜索 AI 工具…"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          onBlur={onClose}
        />
        <InputGroupAddon align="inline-end">
          <InputGroupButton
            type="button"
            size="icon-xs"
            aria-label="关闭搜索"
            title="关闭"
            onMouseDown={(event) => event.preventDefault()}
            onClick={onCancel}
          >
            <X />
          </InputGroupButton>
        </InputGroupAddon>
      </InputGroup>
    </form>
  )
}

interface HeaderProps {
  className?: string
  topics?: readonly Topic[]
  topicCounts?: Record<string, number>
  totalTools?: number
}

function HeaderInner({ className, topics = [], topicCounts = {}, totalTools = 0 }: HeaderProps) {
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchResetKey, setSearchResetKey] = useState(0)
  const searchButtonRef = useRef<HTMLButtonElement>(null)

  const handleSearchClose = () => {
    setSearchOpen(false)
    setSearchResetKey((k) => k + 1)
  }

  /** 显式取消（X / Esc）：关闭并把焦点还给触发按钮；失焦关闭不抢焦点。 */
  const handleSearchCancel = () => {
    handleSearchClose()
    searchButtonRef.current?.focus()
  }

  // 移动端「/」聚焦搜索：仅在本 header 实际可见（<768px）时接管，
  // 桌面端由 MainHeader 处理，避免两个 header 同时挂载造成重复/吞键。
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey) return
      const el = e.target
      if (el instanceof HTMLElement && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable))
        return
      if (window.matchMedia("(min-width: 768px)").matches) return
      e.preventDefault()
      setSearchOpen(true)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  return (
    <header
      className={cn(
        "sticky top-0 z-50 w-full border-b bg-background/95 pt-[env(safe-area-inset-top)] backdrop-blur supports-[backdrop-filter]:bg-background/60",
        className,
      )}
    >
      <div className={pageShell("browse", "flex h-14 items-center justify-between gap-4 px-4 sm:px-6")}>
        <Link
          href="/"
          aria-label="XiGee.net 首页"
          className="shrink-0 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Wordmark size="md" />
        </Link>

        <div className="flex flex-1 items-center justify-end gap-2">
          {searchOpen ? (
            <div id="mobile-search" className="w-full">
              <MobileSearchInput key={searchResetKey} onClose={handleSearchClose} onCancel={handleSearchCancel} />
            </div>
          ) : (
            // 点开的是内联搜索框（不是对话框），所以不声明 aria-haspopup；
            // 触发按钮展开后即卸载，也就没有可挂 aria-expanded 的常驻元素
            <Button
              ref={searchButtonRef}
              variant="outline"
              size="icon"
              aria-label="搜索工具"
              title="搜索"
              onClick={() => setSearchOpen(true)}
            >
              <Search />
            </Button>
          )}

          <MobileMenu topics={topics} topicCounts={topicCounts} totalTools={totalTools} />

          <ThemeToggle />
        </div>
      </div>
    </header>
  )
}

export default function Header(props: HeaderProps) {
  return <HeaderInner {...props} />
}
