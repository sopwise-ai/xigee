import type { Metadata } from "next"
import { getAllTopics, getAllTools } from "@/lib/data"
import { compareIndexRecommended, TOOL_PAGE_SIZE, toToolIndex } from "@/lib/tool"
import type { Tool } from "@/lib/types"
import { ToolBrowser } from "@/components/tool/tool-browser"
import { Hero } from "@/components/hero/hero"

export const metadata: Metadata = {
  alternates: { canonical: "/" },
}

const tools = getAllTools()
const topics = getAllTopics()
const index = tools.map(toToolIndex)
const toolById = new Map(tools.map((tool) => [tool.id, tool]))
const initialTools = [...index]
  .sort(compareIndexRecommended)
  .slice(0, TOOL_PAGE_SIZE)
  .map((tool) => toolById.get(tool.id))
  .filter((tool): tool is Tool => Boolean(tool))

export default function Home() {
  return (
    <div className="flex flex-col gap-8">
      <Hero />
      <ToolBrowser index={index} initialTools={initialTools} pageSize={TOOL_PAGE_SIZE} topics={topics} />
    </div>
  )
}
