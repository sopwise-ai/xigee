"use client"

import { useSyncExternalStore, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { LayoutGrid, History } from "lucide-react"

import { Button } from "@/components/ui/button"
import { BrandMark } from "@/components/brand/brand-mark"
import { Wordmark } from "@/components/brand/wordmark"
import { PanelIcon } from "@/components/brand/panel-icon"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import { storageKey } from "@/lib/storage"
import { topicIconNode } from "@/lib/topic-icon-node"
import { useHistoryCount } from "@/components/history/history-count"
import { formatCount } from "@/lib/format"
import type { Topic } from "@/lib/types"

const STORAGE_KEY = storageKey("sidebar-collapsed")
const COLLAPSE_EVENT = "xigee:sidebar-collapse"

function getSidebarSnapshot() {
  try {
    return localStorage.getItem(STORAGE_KEY) === "true"
  } catch {
    return false
  }
}

function getSidebarServerSnapshot() {
  return false
}

function subscribeSidebar(callback: () => void) {
  const storageHandler = (e: StorageEvent) => {
    // e.key 为 null 表示 localStorage.clear()，此时也需重新读取
    if (e.key !== null && e.key !== STORAGE_KEY) return
    // 其他 tab 折叠变化或清空存储时同步 data-sidebar，保持 CSS 引导一致（SB-01）
    try {
      const next = localStorage.getItem(STORAGE_KEY) === "true"
      document.documentElement.setAttribute("data-sidebar", next ? "collapsed" : "expanded")
    } catch {
      /* noop */
    }
    callback()
  }
  window.addEventListener("storage", storageHandler)
  window.addEventListener(COLLAPSE_EVENT, callback)
  return () => {
    window.removeEventListener("storage", storageHandler)
    window.removeEventListener(COLLAPSE_EVENT, callback)
  }
}

/** 切换折叠状态并同步 <html data-sidebar>（保持与首帧引导 CSS 双轨一致，SB-01） */
function toggleCollapsed(collapsed: boolean) {
  const next = !collapsed
  try {
    localStorage.setItem(STORAGE_KEY, String(next))
  } catch {
    // 隐私模式/配额不足：持久化失败不阻断切换，仅本会话生效
  }
  document.documentElement.setAttribute("data-sidebar", next ? "collapsed" : "expanded")
  window.dispatchEvent(new Event(COLLAPSE_EVENT))
}

/** 折叠态品牌竖轨：居中品牌方块即"打开侧边栏"按钮。
    方块常驻，hover 时方块内浮现实心 panel 图标（对齐 DSH railMark 交互）。 */
function BrandRailToggle() {
  const collapsed = useSyncExternalStore(subscribeSidebar, getSidebarSnapshot, getSidebarServerSnapshot)

  const toggle = () => toggleCollapsed(collapsed)

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={toggle}
      aria-label="打开侧边栏"
      title="打开侧边栏"
      className="group relative mx-auto size-8 shrink-0 overflow-hidden rounded-[9px] border-0 p-0 hover:bg-transparent dark:hover:bg-transparent"
    >
      {/* hover 时瓦片淡出、面板图标淡入 —— 单层渲染，避免两层圆角抗锯齿叠加出暗边 */}
      <BrandMark size="md" className="transition-opacity duration-150 group-hover:opacity-0" />
      <span
        aria-hidden
        className="pointer-events-none absolute inset-0 grid place-items-center opacity-0 transition-opacity duration-150 group-hover:opacity-100"
      >
        <PanelIcon className="size-4 text-primary" />
      </span>
    </Button>
  )
}

/** 展开态顶部收起按钮：28px 圆形 + 实心 panel 图标（对齐 DSH） */
function CollapseToggle() {
  const collapsed = useSyncExternalStore(subscribeSidebar, getSidebarSnapshot, getSidebarServerSnapshot)

  const toggle = () => toggleCollapsed(collapsed)

  return (
    <Button
      variant="ghost"
      size="icon-sm"
      onClick={toggle}
      aria-label={collapsed ? "展开侧边栏" : "收起侧边栏"}
      aria-expanded={!collapsed}
      aria-controls="site-sidebar"
      title={collapsed ? "展开侧边栏" : "收起侧边栏"}
      className="-mr-1 shrink-0 rounded-full text-muted-foreground/70 transition-colors hover:bg-foreground/5 hover:text-foreground"
    >
      <PanelIcon className="size-4" />
    </Button>
  )
}

interface SidebarProps {
  topics: readonly Topic[]
  topicCounts: Record<string, number>
  totalTools: number
}

export function Sidebar({ topics, topicCounts, totalTools }: SidebarProps) {
  const pathname = usePathname()
  const collapsed = useSyncExternalStore(subscribeSidebar, getSidebarSnapshot, getSidebarServerSnapshot)
  const historyCount = useHistoryCount()
  const navRef = useRef<HTMLElement>(null)
  const sentinelRef = useRef<HTMLDivElement>(null)
  const [atBottom, setAtBottom] = useState(true)
  const [scrolled, setScrolled] = useState(false)

  // 标记 hydration 完成，关闭首帧引导 CSS（否则 display:none 会盖过 sr-only）
  // 用 useLayoutEffect 在 paint 前同步设置，消除无障碍盲窗
  useLayoutEffect(() => {
    document.documentElement.setAttribute("data-sidebar-hydrated", "")
  }, [])

  // 底部哨兵：内容未滚到底时显示底部渐隐阴影（scrollable）
  useEffect(() => {
    const nav = navRef.current
    const sentinel = sentinelRef.current
    if (!nav || !sentinel) return
    const observer = new IntersectionObserver(([entry]) => setAtBottom(entry.isIntersecting), {
      root: nav,
      threshold: 0,
    })
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [collapsed])

  // 顶部阴影：向下滚动后，品牌行下方浮出阴影，暗示上方还有内容
  useEffect(() => {
    const nav = navRef.current
    if (!nav) return
    const onScroll = () => setScrolled(nav.scrollTop > 4)
    onScroll()
    nav.addEventListener("scroll", onScroll, { passive: true })
    return () => nav.removeEventListener("scroll", onScroll)
  }, [collapsed])
  // 折叠态 tooltip 由 shadcn Tooltip 组件统一管理（Portal + 定位 + ARIA）

  return (
    <aside
      aria-label="侧边栏"
      id="site-sidebar"
      className={cn(
        "hidden shrink-0 flex-col border-r border-sidebar-border bg-sidebar md:flex",
        collapsed ? "w-14" : "w-[280px]",
        "transition-[width] duration-200",
      )}
    >
      {/* 品牌区：折叠控制恒在品牌行（DSH 式）。
       展开态：mark + XiGee | 收起按钮。
       折叠态：整个品牌区即"打开侧边栏"按钮 —— 仅见 logo，hover LOGO 时浮现展开图标，点击展开。
       下方留出间距，避免与首项图标「连在一起」。 */}
      <div
        className={cn(
          "relative z-10 flex shrink-0 items-center bg-sidebar",
          collapsed ? "justify-center py-2.5" : "h-16 justify-between px-3",
        )}
      >
        {collapsed ? (
          <BrandRailToggle />
        ) : (
          <>
            <Link
              href="/"
              className="flex min-w-0 items-center rounded-lg px-1 py-1.5 outline-none focus-visible:ring-2 focus-visible:ring-ring"
              title="XiGee.net 首页"
            >
              <Wordmark size="lg" />
            </Link>
            <CollapseToggle />
          </>
        )}
      </div>

      {/* 主导航区：占满剩余空间，可滚动 */}
      <div className="relative flex-1 min-h-0">
        <nav
          ref={navRef}
          aria-label="主导航"
          className={cn(
            "flex h-full flex-col overflow-y-auto",
            collapsed ? "gap-1.5 px-2.5 pb-3 pt-3" : "gap-0.5 px-1.5 pb-3 pt-2",
          )}
        >
          {/* 全部工具（核心主功能，首位） */}
          <SidebarLink
            href="/"
            active={pathname === "/"}
            collapsed={collapsed}
            label="全部工具"
            icon={<LayoutGrid className="size-4 shrink-0" />}
            count={formatCount(totalTools)}
          />

          {/* 历史记录（辅助入口） */}
          <SidebarLink
            href="/history"
            active={pathname === "/history"}
            collapsed={collapsed}
            label="历史记录"
            icon={<History className="size-4 shrink-0" />}
            count={formatCount(historyCount)}
          />

          {/* 分组：主导航（全部/历史）与「主题」之间留出呼吸间隔。
              展开态：间距 +「主题」小标题分组；折叠态：极淡居中断线区分两段。 */}
          {collapsed ? (
            <div className="mx-auto my-1.5 h-px w-4 shrink-0 bg-sidebar-border/70" aria-hidden />
          ) : (
            <div className="h-2 shrink-0" aria-hidden />
          )}
          <p data-collapse-hide className={cn("px-3 pb-1.5 font-data text-muted-foreground", collapsed && "sr-only")}>
            主题
          </p>
          {topics.map((topic) => (
            <SidebarLink
              key={topic.id}
              href={`/topic/${topic.id}`}
              active={pathname === `/topic/${topic.id}`}
              collapsed={collapsed}
              label={topic.name}
              icon={topicIconNode(
                topic.icon,
                // 折叠态让位给 [&_svg]:size-5（20px）：emoji 是 span，那个后代选择器对它不生效，
                // 所以这里显式按折叠态给字号，否则折叠轨里 Lucide 20px / emoji 16px 会不齐。
                collapsed ? "text-xl leading-none shrink-0" : "text-base leading-none shrink-0",
              )}
              count={formatCount(topicCounts[topic.id] ?? 0)}
            />
          ))}
          <div ref={sentinelRef} className="h-px" />
        </nav>
        {/* 底部渐隐：未滚到底时暗示下方还有内容 */}
        <div
          aria-hidden
          className={cn(
            "pointer-events-none absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-sidebar via-sidebar/70 to-transparent transition-opacity duration-200",
            atBottom ? "opacity-0" : "opacity-100",
          )}
        />
        {/* 顶部柔和渐隐：向下滚动后浮出，暗示上方还有内容（无边框，仅靠渐变分层） */}
        <div
          aria-hidden
          className={cn(
            "pointer-events-none absolute inset-x-0 top-0 h-4 bg-gradient-to-b from-sidebar to-transparent transition-opacity duration-200",
            scrolled ? "opacity-100" : "opacity-0",
          )}
        />
      </div>
    </aside>
  )
}

interface SidebarLinkProps {
  href: string
  active: boolean
  collapsed: boolean
  label: string
  icon: ReactNode
  count?: string
}

function SidebarLink({ href, active, collapsed, label, icon, count }: SidebarLinkProps) {
  const link = (
    <Link
      href={href}
      prefetch={false}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group relative flex w-full items-center gap-3 rounded-md py-1.5 pl-3 pr-2 text-sm transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring",
        collapsed && "justify-center px-0 py-2.5 [&_svg]:size-5",
        active
          ? "bg-sidebar-accent font-medium text-foreground"
          : "text-muted-foreground hover:bg-sidebar-accent/70 hover:text-foreground",
      )}
    >
      {/* 活跃指示条 */}
      <span
        aria-hidden
        className={cn(
          "absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-brand transition-opacity",
          active ? "opacity-100" : "opacity-0",
        )}
      />
      {icon}
      <span data-collapse-hide className={cn("min-w-0 flex-1 truncate", collapsed && "sr-only")}>
        {label}
      </span>
      {count !== undefined && (
        <span
          data-collapse-hide
          data-sidebar-count
          className={cn(
            "font-data tabular-nums transition-colors",
            collapsed ? "sr-only" : active ? "text-sidebar-accent-foreground/70" : "text-muted-foreground",
          )}
        >
          {count}
        </span>
      )}
    </Link>
  )

  // 折叠态：用 shadcn Tooltip 提供右侧悬浮提示（Portal + 箭头 + 动画，规范实现）
  if (collapsed) {
    return (
      <Tooltip>
        <TooltipTrigger render={link} />
        <TooltipContent side="right" sideOffset={10} align="center" alignOffset={4}>
          {label}
        </TooltipContent>
      </Tooltip>
    )
  }

  return link
}
