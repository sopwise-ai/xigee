"use client"

import { useEffect, useRef } from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { cn } from "@/lib/utils"
import { pageShell } from "@/lib/layout"
import { isInfoRoute } from "@/components/info/info-nav"
import type { Topic } from "@/lib/types"

interface SubNavProps {
  className?: string
  topics: readonly Topic[]
}

export function SubNav({ className, topics }: SubNavProps) {
  const pathname = usePathname()
  const firstRun = useRef(true)
  const scrollRef = useRef<HTMLDivElement>(null)

  // 仅在本导航容器内查找激活项：避免命中侧栏（移动端 display:none）的同名 aria-current 而空滚（SN-01）
  useEffect(() => {
    const el = scrollRef.current?.querySelector<HTMLElement>('[aria-current="page"]')
    if (el) {
      // 首次加载瞬时定位（避免首帧横向滑动闪烁），后续路由切换平滑滚动
      el.scrollIntoView({ behavior: firstRun.current ? "auto" : "smooth", inline: "center", block: "nearest" })
    }
    firstRun.current = false
  }, [pathname])

  // 信息页在移动端有自己的二级栏：不再叠一条主题条，避免两条横栏堆在顶栏下
  if (isInfoRoute(pathname)) return null

  return (
    <nav
      aria-label="主题导航"
      className={cn(
        "sticky top-[calc(3.5rem_+_env(safe-area-inset-top))] z-40 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60",
        className,
      )}
    >
      <div className={pageShell("browse", "relative px-4 sm:px-6")}>
        <div ref={scrollRef} className="no-scrollbar -ml-1 flex items-center gap-1 overflow-x-auto py-2 pr-8 pl-1">
          <Link
            href="/"
            prefetch={false}
            aria-current={pathname === "/" ? "page" : undefined}
            className={cn(
              "shrink-0 rounded-md px-3 py-1.5 text-sm transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring",
              pathname === "/"
                ? "bg-brand/10 font-medium text-brand"
                : "text-muted-foreground hover:bg-brand/5 hover:text-brand",
            )}
          >
            全部
          </Link>
          {topics.map((topic) => {
            const isActive = pathname === `/topic/${topic.id}`
            return (
              <Link
                key={topic.id}
                href={`/topic/${topic.id}`}
                prefetch={false}
                aria-current={isActive ? "page" : undefined}
                className={cn(
                  "shrink-0 rounded-md px-3 py-1.5 text-sm transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  isActive
                    ? "bg-brand/10 font-medium text-brand"
                    : "text-muted-foreground hover:bg-brand/5 hover:text-brand",
                )}
              >
                {topic.name}
              </Link>
            )
          })}
        </div>
        <div className="pointer-events-none absolute right-4 top-0 bottom-0 w-8 bg-gradient-to-l from-background to-transparent sm:right-6" />
      </div>
    </nav>
  )
}
