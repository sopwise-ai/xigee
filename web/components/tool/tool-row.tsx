import { ArrowUpRight } from "lucide-react"
import type { Tool } from "@/lib/types"
import { toolHistoryAttrs } from "@/lib/tool"
import { Badge } from "@/components/ui/badge"
import { PricingBadge } from "@/components/tool/pricing-badge"
import { topicIconNode } from "@/lib/topic-icon-node"
import { getDomain } from "@/lib/url"
import { cn } from "@/lib/utils"

const MAX_TAGS = 2

export function ToolRow({
  tool,
  last = false,
  topicLabel,
  topicIcon,
}: {
  tool: Tool
  last?: boolean
  topicLabel?: string
  topicIcon?: string
}) {
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
      className={cn(
        "group flex items-center gap-3 px-4 py-3.5 transition-colors hover:bg-secondary/50 outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset",
        !last && "border-b border-border",
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="shrink-0 truncate text-lg font-semibold tracking-tight">{tool.name}</span>
          {topicLabel && (
            <span
              className="hidden shrink-0 items-center gap-1 font-data text-muted-foreground sm:inline-flex"
              title={topicLabel}
            >
              {topicIcon ? topicIconNode(topicIcon, "text-xs leading-none shrink-0") : null}
              {topicLabel}
            </span>
          )}
          <span className="hidden shrink-0 font-data text-muted-foreground md:inline">{domain}</span>
        </div>
        <p className="truncate text-sm text-muted-foreground" title={tool.description}>
          {tool.description}
        </p>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        {shownTags.length > 0 && (
          <div className="hidden items-center gap-1 md:flex">
            {shownTags.map((tag) => (
              <Badge key={tag} variant="secondary" className="max-w-[6rem] truncate px-1.5 py-0 text-xs font-normal">
                {tag}
              </Badge>
            ))}
            {extraTags > 0 && (
              <Badge variant="secondary" className="px-1.5 py-0 text-xs font-normal text-muted-foreground">
                +{extraTags}
              </Badge>
            )}
          </div>
        )}
        {tool.pricing && <PricingBadge pricing={tool.pricing} />}
        <ArrowUpRight
          className="size-3.5 shrink-0 text-muted-foreground/60 transition group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-foreground"
          aria-hidden
        />
        <span className="sr-only">（在新标签页打开官网）</span>
      </div>
    </a>
  )
}
