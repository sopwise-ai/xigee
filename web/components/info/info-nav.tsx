"use client"

import { useEffect, useRef } from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { FileText, Info, Settings, ShieldCheck, type LucideIcon } from "lucide-react"
import { cn } from "@/lib/utils"

const ITEMS: { href: string; label: string; icon: LucideIcon }[] = [
  { href: "/settings", label: "设置", icon: Settings },
  { href: "/about", label: "关于", icon: Info },
  { href: "/privacy", label: "隐私政策", icon: ShieldCheck },
  { href: "/terms", label: "服务条款", icon: FileText },
]

/** 信息区路由：供全站判断「这是信息页」（如移动端不显示主题条）。 */
export const INFO_ROUTES: readonly string[] = ITEMS.map((item) => item.href)

export function isInfoRoute(pathname: string): boolean {
  return INFO_ROUTES.includes(pathname)
}

/**
 * 信息区导航：放在二级栏（PageBar）左槽里，窄屏横向滚动。
 * 选中态沿用全站既有的切换器语言（bg-brand/10 + 品牌色文字），与工具筛选、主题条一致。
 */
export function InfoNav({ className }: { className?: string }) {
  const pathname = usePathname()
  const navRef = useRef<HTMLElement>(null)

  // 窄屏放不下时横向滚动：把当前页自动滚入可视区，用户一眼看到自己在哪一项
  useEffect(() => {
    const el = navRef.current?.querySelector<HTMLElement>('[aria-current="page"]')
    el?.scrollIntoView({ behavior: "auto", inline: "center", block: "nearest" })
  }, [pathname])

  return (
    <nav
      ref={navRef}
      aria-label="信息导航"
      // 不自己做滚动容器：滚动交给外层二级栏的槽（两层 overflow 会把焦点环裁两次）
      className={cn("flex items-center gap-1", className)}
    >
      {ITEMS.map(({ href, label, icon: Icon }) => {
        const active = pathname === href
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "group relative flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm sm:gap-2 sm:px-3 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring",
              active ? "bg-brand/10 font-medium text-brand" : "text-muted-foreground hover:bg-brand/5 hover:text-brand",
            )}
          >
            <Icon className="hidden size-4 shrink-0 sm:block" aria-hidden />
            <span className="whitespace-nowrap">{label}</span>
            {active && <span className="sr-only">（当前页）</span>}
          </Link>
        )
      })}
    </nav>
  )
}
