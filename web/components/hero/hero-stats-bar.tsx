import { cn } from "@/lib/utils"
import { formatCount } from "@/lib/format"
import type { HeroStats } from "@/components/hero/types"

/** Hero 实时统计条：发丝分隔，等宽数字，克制的精致感。 */
export function HeroStatsBar({ stats, className }: { stats: HeroStats; className?: string }) {
  const items: [string, number][] = [
    ["工具", stats.tools],
    ["主题", stats.topics],
    ["精选", stats.featured],
  ]

  return (
    <dl className={cn("flex flex-wrap items-center gap-x-4 gap-y-1.5 sm:gap-x-8 sm:gap-y-2", className)}>
      {items.map(([label, value], i) => (
        <div
          key={label}
          className={cn(
            "flex items-baseline gap-2",
            i > 0 &&
              "relative pl-4 before:absolute before:left-0 sm:pl-8 before:top-[0.1em] before:h-[1.1em] before:w-px before:bg-border/80",
          )}
        >
          <dt className="text-xs tracking-wide text-muted-foreground">{label}</dt>
          <dd className="order-first font-mono text-lg leading-none font-medium sm:text-xl tabular-nums tracking-tight text-foreground">
            {formatCount(value)}
          </dd>
        </div>
      ))}
    </dl>
  )
}
