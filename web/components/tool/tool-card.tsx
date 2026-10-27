import type { Tool } from "@/lib/types"
import { getDomain } from "@/lib/url"
import { toolHistoryAttrs } from "@/lib/tool"
import { Badge } from "@/components/ui/badge"
import { PricingBadge } from "@/components/tool/pricing-badge"
import { topicIconNode } from "@/lib/topic-icon-node"
import { ArrowUpRight } from "lucide-react"

interface ToolCardProps {
  tool: Tool
  /** 主题展示信息（名称 + 图标），缺省时仅显示域名。 */
  topicLabel?: string
  topicIcon?: string
}

const MAX_TAGS = 3

export function ToolCard({ tool, topicLabel, topicIcon }: ToolCardProps) {
  const domain = getDomain(tool.url)
  const tags = tool.tags ?? []
  const shownTags = tags.slice(0, MAX_TAGS)
  const extraTags = tags.length - shownTags.length

  return (
    <a
      href={tool.url}
      target="_blank"
      rel="noopener noreferrer"
      {...toolHistoryAttrs(tool)}
      title={tool.name}
      className="group flex flex-col gap-3 rounded-lg border border-border bg-card p-4 outline-none transition-colors hover:border-foreground/15 hover:bg-secondary/50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
    >
      <div className="min-w-0">
        <div className="flex items-start justify-between gap-2">
          <h2 className="truncate text-lg font-semibold tracking-tight text-foreground">{tool.name}</h2>
          <ArrowUpRight
            className="mt-1 size-4 shrink-0 text-muted-foreground/50 transition group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-foreground"
            aria-hidden
          />
          <span className="sr-only">（在新标签页打开官网）</span>
        </div>
        {/* 固定两行：不足两行也保留高度，保证网格卡片等高对齐 */}
        <p className="mt-1.5 line-clamp-2 min-h-[2.75rem] text-sm leading-relaxed text-muted-foreground">
          {tool.description}
        </p>
      </div>

      {/* 主题 + 标签：限量展示，超出以 +N 收纳，避免多标签/多主题撑破卡片 */}
      <div className="flex flex-wrap items-center gap-1">
        {topicLabel && (
          <Badge
            variant="outline"
            className="gap-1 px-1.5 py-0 text-xs font-normal text-muted-foreground"
            title={topicLabel}
          >
            {topicIcon ? topicIconNode(topicIcon, "text-xs leading-none shrink-0") : null}
            <span className="max-w-[7rem] truncate">{topicLabel}</span>
          </Badge>
        )}
        {shownTags.map((tag) => (
          <Badge key={tag} variant="secondary" className="max-w-[7rem] truncate px-1.5 py-0 text-xs font-normal">
            {tag}
          </Badge>
        ))}
        {extraTags > 0 && (
          <Badge variant="secondary" className="px-1.5 py-0 text-xs font-normal text-muted-foreground">
            +{extraTags}
          </Badge>
        )}
      </div>

      <div className="mt-auto flex items-center justify-between">
        {tool.pricing ? (
          <PricingBadge pricing={tool.pricing} />
        ) : (
          <span className="font-data text-muted-foreground">—</span>
        )}
        <span className="font-data text-xs text-muted-foreground">{domain}</span>
      </div>
    </a>
  )
}
