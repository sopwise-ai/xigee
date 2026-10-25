import type { Meta, StoryObj } from "@storybook/nextjs-vite"
import { ToolBrowser } from "@/components/tool/tool-browser"
import { mockToolIndex, mockTools } from "@/.storybook/fixtures"

const meta = {
  title: "Tool/ToolBrowser",
  component: ToolBrowser,
  tags: ["autodocs"],
  args: { index: mockToolIndex, initialTools: mockTools, pageSize: 60 },
  // 渲染前清除持久化偏好，避免上一个 story 的 view/sort 泄露到本 story 首帧
  beforeEach: () => {
    try {
      localStorage.removeItem("xigee:default-view")
      localStorage.removeItem("xigee:default-sort")
    } catch {
      /* noop */
    }
  },
} satisfies Meta<typeof ToolBrowser>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {}

export const ListView: Story = {
  args: { defaultView: "list" },
}

export const WithoutTabs: Story = {
  args: { showTabs: false },
}

export const Empty: Story = {
  args: {
    index: [],
    initialTools: [],
    emptyTitle: "该主题暂无工具",
    emptyDescription: "换个主题看看吧",
  },
}
