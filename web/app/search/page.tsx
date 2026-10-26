import type { Metadata } from "next"
import { Suspense } from "react"
import { getAllTopics, getTopicCounts, getFeaturedTools } from "@/lib/data"
import { pageShell } from "@/lib/layout"
import { SearchResults } from "@/components/search/search-results"
import { Skeleton } from "@/components/ui/skeleton"

export const metadata: Metadata = {
  title: "搜索",
  // noindex 页面不声明 canonical：索引已拒绝收录，再给规范地址属于多余信号
  openGraph: { title: "搜索" },
  robots: { index: false, follow: true },
}

const featured = getFeaturedTools()
const topics = getAllTopics()
const topicCounts = getTopicCounts()

/**
 * 搜索由 /api/search 服务端计算（query 来自 URL），SSR 呈现同构骨架，避免「加载中…→结果」突兀跳变。
 *
 * 骨架形状要与最终布局对齐（计数行 + 结果列表），否则 hydrate 完成时会出现一次明显的位置跳变。
 */
function ResultsSkeleton() {
  return (
    <div className="flex flex-col gap-3" aria-busy="true">
      <div className="flex items-center justify-between gap-3">
        <Skeleton className="h-5 w-52 rounded" />
        <Skeleton className="h-8 w-24 rounded-lg" />
      </div>
      <div className="overflow-hidden rounded-lg border bg-card">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="flex items-center gap-3 border-b border-border px-4 py-3 last:border-b-0">
            <div className="flex min-w-0 flex-1 flex-col gap-1.5">
              <Skeleton className="h-4 w-1/4 rounded" />
              <Skeleton className="h-3 w-3/4 rounded" />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function SearchPage() {
  return (
    <div className={pageShell("content", "flex flex-col gap-4")}>
      <h1 className="text-2xl font-semibold tracking-tight">搜索</h1>
      <Suspense fallback={<ResultsSkeleton />}>
        <SearchResults featured={featured} topics={topics} topicCounts={topicCounts} />
      </Suspense>
    </div>
  )
}
