"use client"

import { useEffect, useRef, useState } from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { History, LayoutGrid, Menu, Settings, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { formatCount } from "@/lib/format"
import { useHistoryCount } from "@/components/history/history-count"
import type { Topic } from "@/lib/types"

interface MobileMenuProps {
  topics: readonly Topic[]
  topicCounts: Record<string, number>
  totalTools: number
}

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
      <Button
        ref={triggerRef}
        variant="outline"
        size="icon"
        aria-label="打开菜单"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls="mobile-menu"
        onClick={() => setOpen(true)}
      >
        <Menu aria-hidden />
      </Button>

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
              <Button ref={closeRef} variant="ghost" size="icon" aria-label="关闭菜单" onClick={close}>
                <X aria-hidden />
              </Button>
            </div>

            <div className="shrink-0 px-3 pt-3">
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
                <MenuLink href="/settings" icon={Settings} label="设置" active={pathname === "/settings"} />
              </nav>
            </div>

            <div className="mt-3 flex min-h-0 flex-1 flex-col border-t">
              <div className="flex shrink-0 items-baseline justify-between px-5 pb-1 pt-3">
                <p className="font-data text-[0.6875rem] uppercase tracking-[0.18em] text-muted-foreground">主题</p>
                <span className="font-data text-[0.6875rem] text-muted-foreground">{topics.length}</span>
              </div>
              <nav aria-label="全部主题" className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 pb-4">
                <div className="flex flex-col gap-0.5">
                  {topics.map((topic) => {
                    const active = pathname === `/topic/${topic.id}`
                    return (
                      <Link
                        key={topic.id}
                        href={`/topic/${topic.id}`}
                        prefetch={false}
                        aria-current={active ? "page" : undefined}
                        className={cn(
                          "flex min-w-0 items-center justify-between gap-3 rounded-md px-2 py-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring",
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
                </div>
              </nav>
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
