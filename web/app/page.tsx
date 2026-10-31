import type { Metadata } from "next"
import { getAllTopics, getAllTools } from "@/lib/data"
import { getInitialToolIds, TOOL_PAGE_SIZE } from "@/lib/tool"
import type { Tool } from "@/lib/types"
import { ToolBrowser } from "@/components/tool/tool-browser"
import { Hero } from "@/components/hero/hero"

export const metadata: Metadata = {
  alternates: { canonical: "/" },
}

const tools = getAllTools()
const topics = getAllTopics()
const toolById = new Map(tools.map((tool) => [tool.id, tool]))
// 首屏只带默认排序的第一页；轻量索引由 /api/index 在 hydration 后按需拉取
const initialTools = getInitialToolIds(
  tools.map((tool) => ({ id: tool.id, name: tool.name, featured: tool.featured })),
  TOOL_PAGE_SIZE,
)
  .map((id) => toolById.get(id))
  .filter((tool): tool is Tool => Boolean(tool))

export default function Home() {
  return (
    <div className="flex flex-col gap-8">
      <Hero />
      <ToolBrowser initialTools={initialTools} pageSize={TOOL_PAGE_SIZE} topics={topics} />
    </div>
  )
}
