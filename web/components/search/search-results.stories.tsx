import { Suspense } from "react"
import type { Meta, StoryObj } from "@storybook/nextjs-vite"
import { SearchResults } from "@/components/search/search-results"
import { mockTopicCounts, mockTopics, mockTools } from "@/.storybook/fixtures"

const featured = mockTools.filter((p) => p.featured)

const meta = {
  title: "Search/SearchResults",
  component: SearchResults,
  tags: ["autodocs"],
  args: { featured, topics: mockTopics, topicCounts: mockTopicCounts },
  decorators: [
    (Story) => (
      <Suspense fallback={<div className="text-sm text-muted-foreground">加载中…</div>}>
        <Story />
      </Suspense>
    ),
  ],
} satisfies Meta<typeof SearchResults>

export default meta
type Story = StoryObj<typeof meta>

/** 空查询：着陆态 —— 最近搜索（有则显示）/ 试试这些 / 按主题浏览 */
export const Landing: Story = {
  parameters: { nextjs: { appDirectory: true, navigation: { query: {} } } },
}

/** 有结果：主题 facet + 排序 + 带命中上下文的结果行 */
export const WithResults: Story = {
  parameters: { nextjs: { appDirectory: true, navigation: { query: { q: "对话" } } } },
}

/** 未找到但「确实沾边」：走「也许你想找」 */
export const Maybe: Story = {
  parameters: { nextjs: { appDirectory: true, navigation: { query: { q: "画图" } } } },
}

/** 完全无关：不硬凑结果，退回精选推荐 + 主题出口 */
export const NoResults: Story = {
  parameters: { nextjs: { appDirectory: true, navigation: { query: { q: "zzzznotfound" } } } },
}
