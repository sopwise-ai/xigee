"use client"

import { useEffect, useRef, useState } from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { FileText, History, Info, LayoutGrid, Menu, Settings, Shield, X } from "lucide-react"
import { cn } from "@/lib/utils"
import { formatCount } from "@/lib/format"
import { useHistoryCount } from "@/components/history/history-count"
import type { Topic } from "@/lib/types"

interface MobileMenuProps {
  topics: readonly Topic[]
  topicCounts: Record<string, number>
  totalTools: number
}

const INFO_LINKS = [
  { href: "/settings", label: "设置", icon: Settings },
  { href: "/about", label: "关于 XiGee", icon: Info },
  { href: "/privacy", label: "隐私政策", icon: Shield },
  { href: "/terms", label: "服务条款", icon: FileText },
] as const

/**
 * 移动端主导航抽屉。
 *
 * 用原生 `<dialog>`：焦点陷阱、Esc 关闭、关闭后焦点归还触发按钮都由浏览器保证，
 * 比自建 div + keydown 更稳，也不用额外引入 Dialog 依赖。背景滚动在打开时锁住。
 */
export function MobileMenu({ topics, topicCounts, totalTools }: MobileMenuProps) {
  const [open, setOpen] = useState(false)
  const dialogRef = useRef<HTMLDialogElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const pathname = usePathname()
  const historyCount = useHistoryCount()

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (open && !dialog.open) {
      dialog.showModal()
      closeRef.current?.focus()
    }
    if (!open && dialog.open) dialog.close()
  }, [open])

  // 路由变化后收起（点抽屉里的链接）。close 事件里再同步 React state，避免在 effect 里直接 setState。
  useEffect(() => {
    if (dialogRef.current?.open) dialogRef.current.close()
  }, [pathname])

  useEffect(() => {
    if (!open) return
    const previous = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      document.body.style.overflow = previous
    }
  }, [open])

  const close = () => {
    setOpen(false)
    triggerRef.current?.focus()
  }

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        aria-label="打开菜单"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls="mobile-menu"
        onClick={() => setOpen(true)}
        className="inline-flex size-9 items-center justify-center rounded-md border border-input bg-background text-foreground transition-colors outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Menu className="size-4" aria-hidden />
      </button>

      <dialog
        ref={dialogRef}
        id="mobile-menu"
        aria-label="站点导航"
        onClose={() => setOpen(false)}
        onClick={(event) => {
          // 点遮罩（dialog 本身）关闭；点面板内部不处理
          if (event.target === dialogRef.current) close()
        }}
        className="fixed inset-0 z-[80] m-0 h-full max-h-none w-full max-w-none bg-transparent p-0 backdrop:bg-black/40"
      >
        {open && (
          <div className="ml-auto flex h-[100dvh] w-[86%] max-w-sm flex-col border-l bg-background shadow-2xl">
            <div className="flex h-14 shrink-0 items-center justify-between border-b px-4">
              <span className="text-sm font-semibold tracking-tight">导航</span>
              <button
                ref={closeRef}
                type="button"
                aria-label="关闭菜单"
                onClick={close}
                className="inline-flex size-9 items-center justify-center rounded-md text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
              >
                <X className="size-4" aria-hidden />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto overscroll-contain px-3 py-3">
              <nav aria-label="快捷入口" className="flex flex-col gap-0.5">
                <MenuLink
                  href="/"
                  icon={LayoutGrid}
                  label="全部工具"
                  count={formatCount(totalTools)}
                  active={pathname === "/"}
                />
                <MenuLink
                  href="/history"
                  icon={History}
                  label="历史记录"
                  count={formatCount(historyCount)}
                  active={pathname === "/history"}
                />
              </nav>

              <div className="mt-4 flex items-baseline justify-between px-2">
                <p className="font-data text-[0.6875rem] uppercase tracking-[0.18em] text-muted-foreground">主题</p>
                <span className="font-data text-[0.6875rem] text-muted-foreground">{topics.length}</span>
              </div>
              <nav aria-label="全部主题" className="mt-1 grid grid-cols-2 gap-0.5">
                {topics.map((topic) => {
                  const active = pathname === `/topic/${topic.id}`
                  return (
                    <Link
                      key={topic.id}
                      href={`/topic/${topic.id}`}
                      prefetch={false}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "flex min-w-0 items-center justify-between gap-1 rounded-md px-2 py-1.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        active
                          ? "bg-brand/10 font-medium text-brand"
                          : "text-muted-foreground hover:bg-accent hover:text-foreground",
                      )}
                    >
                      <span className="truncate">{topic.name}</span>
                      <span className="shrink-0 font-data text-[0.6875rem] text-muted-foreground">
                        {formatCount(topicCounts[topic.id] ?? 0)}
                      </span>
                    </Link>
                  )
                })}
              </nav>

              <div className="mt-4 border-t pt-3">
                <p className="px-2 font-data text-[0.6875rem] uppercase tracking-[0.18em] text-muted-foreground">
                  更多
                </p>
                <nav aria-label="更多" className="mt-1 flex flex-col gap-0.5">
                  {INFO_LINKS.map(({ href, label, icon: Icon }) => (
                    <MenuLink key={href} href={href} icon={Icon} label={label} active={pathname === href} />
                  ))}
                </nav>
              </div>
            </div>
          </div>
        )}
      </dialog>
    </>
  )
}

function MenuLink({
  href,
  icon: Icon,
  label,
  count,
  active,
}: {
  href: string
  icon: typeof LayoutGrid
  label: string
  count?: string
  active?: boolean
}) {
  return (
    <Link
      href={href}
      prefetch={false}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-center gap-3 rounded-md px-2 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active ? "bg-brand/10 font-medium text-brand" : "text-muted-foreground hover:bg-accent hover:text-foreground",
      )}
    >
      <Icon className="size-4 shrink-0" aria-hidden />
      <span className="flex-1">{label}</span>
      {count && <span className="font-data text-[0.6875rem] text-muted-foreground">{count}</span>}
    </Link>
  )
}
