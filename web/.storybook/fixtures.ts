import { buildSuggestionDocs } from "@/lib/search"
import { toToolIndex } from "@/lib/tool"
import type { Topic, Tool } from "@/lib/types"

/** Storybook 共享 mock 数据（仅用于 stories，不参与生产构建）。 */

export const mockTopics: Topic[] = [
  { id: "chat-assistant", name: "对话助手", icon: "💬" },
  { id: "image-generation", name: "图像生成", icon: "🖼️" },
  { id: "code-tools", name: "代码工具", icon: "💻" },
  { id: "writing-tools", name: "写作工具", icon: "✍️" },
  { id: "video-tools", name: "视频工具", icon: "🎬" },
]

export const mockTopicCounts: Record<string, number> = {
  "chat-assistant": 7,
  "image-generation": 7,
  "code-tools": 7,
  "writing-tools": 5,
  "video-tools": 5,
}

export const mockTool: Tool = {
  id: "openai-chatgpt",
  name: "ChatGPT",
  description: "OpenAI 推出的对话式 AI 助手，支持文本生成、代码编写与多轮对话。",
  url: "https://chat.openai.com",
  topics: ["chat-assistant"],
  tags: ["对话", "文本生成", "OpenAI"],
  pricing: "freemium",
  featured: true,
  publishedAt: "2026-01-15",
  createdAt: "2026-01-10",
}

export const mockTools: Tool[] = [
  mockTool,
  {
    id: "anthropic-claude",
    name: "Claude",
    description: "Anthropic 的 AI 助手，擅长长文本理解、分析与安全对齐。",
    url: "https://claude.ai",
    topics: ["chat-assistant"],
    tags: ["对话", "长文本"],
    pricing: "freemium",
    featured: true,
    publishedAt: "2026-02-01",
  },
  {
    id: "midjourney",
    name: "Midjourney",
    description: "高质量 AI 图像生成工具，以艺术风格与画面质感见长。",
    url: "https://www.midjourney.com",
    topics: ["image-generation"],
    tags: ["图像", "绘画"],
    pricing: "paid",
    publishedAt: "2026-01-20",
  },
  {
    id: "stable-diffusion",
    name: "Stable Diffusion",
    description: "开源文生图模型，可本地部署，生态与插件丰富。",
    url: "https://stability.ai",
    topics: ["image-generation"],
    tags: ["图像", "开源"],
    pricing: "opensource",
    publishedAt: "2026-01-05",
  },
  {
    id: "github-copilot",
    name: "GitHub Copilot",
    description: "AI 编程助手，在编辑器中实时补全代码与生成测试。",
    url: "https://github.com/features/copilot",
    topics: ["code-tools"],
    tags: ["编程", "补全"],
    pricing: "paid",
    featured: true,
    publishedAt: "2026-02-10",
  },
]

export const mockSuggestions = ["对话助手", "图像生成", "代码工具", "写作工具"]

export const mockToolIndex = mockTools.map(toToolIndex)

/** 顶栏搜索建议数据（由工具 + 主题名展开，与根布局下发的同源）。 */
export const mockSuggestionDocs = buildSuggestionDocs(
  mockTools,
  Object.fromEntries(mockTopics.map((t) => [t.id, t.name])),
)
