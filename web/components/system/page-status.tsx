import type { ReactNode } from "react"
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia } from "@/components/ui/empty"
import { cn } from "@/lib/utils"

interface PageStatusProps {
  /** 状态码 / 眉标，mono 大写显示，如 "404" / "ERROR"。 */
  code: string
  /** 媒体区图标元素（如 <Compass />）。 */
  media: ReactNode
  title: string
  description: ReactNode
  /** 动作区（按钮 / 链接）。 */
  actions?: ReactNode
  /** 额外内容（搜索、主题等）。 */
  children?: ReactNode
  /** 语义角色，错误页传 "alert" 以便即时播报。 */
  role?: "alert" | "status"
  className?: string
}

/**
 * 状态页共享外壳：克制的居中留白版式（shadcn Empty），无卡片/背景。
 * 供 404 / 错误页共用，保证两页视觉一致；Server-safe（无 hooks）。
 */
export function PageStatus({ code, media, title, description, actions, children, role, className }: PageStatusProps) {
  return (
    <section
      role={role}
      className={cn(
        "mx-auto flex min-h-[60vh] w-full max-w-xl flex-col items-center justify-center px-6 py-16",
        className,
      )}
    >
      <Empty className="gap-5">
        <EmptyMedia variant="icon" className="size-14 rounded-2xl [&_svg:not([class*='size-'])]:size-6">
          {media}
        </EmptyMedia>
        <EmptyHeader className="gap-3">
          <p className="font-data text-xs uppercase tracking-[0.22em] text-muted-foreground">{code}</p>
          <h1 className="m-0 font-brand text-3xl font-semibold tracking-tight text-balance">{title}</h1>
          <EmptyDescription>{description}</EmptyDescription>
        </EmptyHeader>
        {actions ? <EmptyContent className="gap-3">{actions}</EmptyContent> : null}
        {children}
      </Empty>
    </section>
  )
}
