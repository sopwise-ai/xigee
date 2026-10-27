import { type Metadata } from "next"
import { notFound } from "next/navigation"
import { getAllTopics, getTopicById, getToolsByTopic } from "@/lib/data"
import { getInitialToolIds, latestToolDate, TOOL_PAGE_SIZE } from "@/lib/tool"
import { topicIconNode } from "@/lib/topic-icon-node"
import { formatCount, formatDate } from "@/lib/format"
import { getBaseUrl } from "@/lib/utils"
import type { Tool } from "@/lib/types"
import { ToolBrowser } from "@/components/tool/tool-browser"

type Props = {
  params: Promise<{ id: string }>
}

export async function generateStaticParams() {
  const topics = getAllTopics()
  return topics.map((topic) => ({
    id: topic.id,
  }))
}

export const dynamicParams = false

// 注：dynamicParams=false 时，未在 generateStaticParams 中列出的 id 由 Next 直接 404，
// 下面 generateMetadata 的「主题未找到」分支与页面里的 notFound() 实际不会执行
// —— 仅作类型收窄与数据意外缺失时的防御保留。

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params
  const topic = getTopicById(id)
  if (!topic) return { title: "主题未找到", robots: { index: false, follow: true } }
  const description = `发现和浏览「${topic.name}」主题下的 AI 工具，XiGee 为你精选最佳选择`
  const empty = getToolsByTopic(id).length === 0
  return {
    title: `${topic.name}`,
    description,
    alternates: { canonical: `/topic/${id}` },
    openGraph: { title: `${topic.name} — XiGee`, description },
    ...(empty ? { robots: { index: false, follow: true } } : {}),
  }
}

export default async function TopicPage({ params }: Props) {
  const { id } = await params
  const topic = getTopicById(id)
  if (!topic) notFound()

  const tools = getToolsByTopic(id)
  const latestDate = latestToolDate(tools)
  const toolById = new Map(tools.map((tool) => [tool.id, tool]))
  const initialTools = getInitialToolIds(
    tools.map((tool) => ({ id: tool.id, name: tool.name, featured: tool.featured })),
    TOOL_PAGE_SIZE,
  )
    .map((id) => toolById.get(id))
    .filter((tool): tool is Tool => Boolean(tool))

  const baseUrl = getBaseUrl()
  const breadcrumbLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "全部工具", item: baseUrl },
      { "@type": "ListItem", position: 2, name: topic.name, item: `${baseUrl}/topic/${id}` },
    ],
  }
  const itemListLd = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name: `${topic.name} — XiGee`,
    itemListElement: tools.map((p, i) => ({
      "@type": "ListItem",
      position: i + 1,
      name: p.name,
      url: p.url,
    })),
  }
  // JSON-LD 注入前转义 `<`，避免工具/主题名中的 </script> 提前闭合脚本标签
  const ld = (obj: unknown) => JSON.stringify(obj).replace(/</g, "\\u003c")

  return (
    <div className="flex flex-col gap-4">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: ld(breadcrumbLd) }} />
      {tools.length > 0 && <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: ld(itemListLd) }} />}

      <ToolBrowser
        initialTools={initialTools}

        topic={id}
        pageSize={TOOL_PAGE_SIZE}
        topics={getAllTopics()}
        defaultView="grid"
        showTabs={false}
        emptyTitle={`「${topic.name}」主题暂无工具收录`}
        emptyDescription="你可以浏览其他主题发现更多 AI 工具"
        title={
          <div className="flex min-w-0 items-center gap-3">
            <span
              key="icon"
              className="flex size-8 shrink-0 items-center justify-center rounded-md border bg-card text-foreground"
            >
              {topicIconNode(topic.icon, "text-base leading-none shrink-0")}
            </span>
            {/* 主题名即本页 h1（放进二级栏视觉标题位，不再另设 sr-only h1）；数量/日期为附属信息 */}
            <h1 key="name" className="min-w-0 truncate text-base font-semibold tracking-tight">
              {topic.name}
            </h1>
            {/* 窄屏二级栏空间有限：数量让位给主题名（主题条里本来就带数量） */}
            <span key="count" className="hidden shrink-0 font-data text-xs font-normal text-muted-foreground sm:inline">
              {formatCount(tools.length)} 个工具
            </span>
            {latestDate && (
              <span
                key="date"
                className="hidden shrink-0 font-data text-xs font-normal text-muted-foreground/70 sm:inline"
              >
                · 最近更新 {formatDate(latestDate)}
              </span>
            )}
          </div>
        }
      />
    </div>
  )
}
