import { describe, it, expect, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import { SearchSuggestions, suggestionOptionId } from "./search-suggestions"
import type { SuggestionDoc } from "@/lib/search"

const docs: SuggestionDoc[] = [
  {
    id: "chatgpt",
    name: "ChatGPT",
    url: "https://chat.openai.com",
    topics: ["chat-assistant"],
    topicNames: ["对话助手"],
    tags: ["对话"],
    pricing: "freemium",
  },
  {
    id: "midjourney",
    name: "Midjourney",
    url: "https://www.midjourney.com",
    topics: ["image-generation"],
    topicNames: ["图像生成"],
    tags: ["图像"],
    pricing: "paid",
  },
]

describe("SearchSuggestions", () => {
  it("渲染每条建议：名称 + 主题 + 域名，并带上历史埋点属性", () => {
    render(<SearchSuggestions items={docs} query="chat" activeIndex={-1} listboxId="lb" />)

    const options = within(screen.getByRole("listbox", { name: "搜索建议" })).getAllByRole("option")
    expect(options).toHaveLength(2)
    expect(screen.getByText("对话助手")).toBeInTheDocument()
    expect(screen.getByText("图像生成")).toBeInTheDocument()
    expect(screen.getByText("chat.openai.com")).toBeInTheDocument()
    expect(screen.getByText("Midjourney").closest("a")).toHaveAttribute("data-history-id", "midjourney")
  })

  it("命中片段用 <mark> 高亮，与结果页同一套分段规则", () => {
    const { container } = render(<SearchSuggestions items={docs} query="chat" activeIndex={-1} listboxId="lb" />)
    const marks = container.querySelectorAll("mark")
    expect(marks).toHaveLength(1)
    expect(marks[0].textContent).toBe("Chat")
  })

  it("activeIndex 指向的选项 aria-selected=true，其余为 false", () => {
    render(<SearchSuggestions items={docs} query="chat" activeIndex={1} listboxId="lb" />)
    const options = screen.getAllByRole("option")
    expect(options[0]).toHaveAttribute("aria-selected", "false")
    expect(options[1]).toHaveAttribute("aria-selected", "true")
    expect(options[1]).toHaveAttribute("id", suggestionOptionId("lb", 1))
  })

  it("option 就是可点击的链接本身：aria-activedescendant 必须指向 <a> 而非外层容器", () => {
    // 回归：id 曾挂在包一层的 <li> 上，`getElementById(id).click()` 点不到链接，
    // 于是「选中建议后回车打开」静默失效。这里锁住 id/role 必须落在 <a> 上。
    render(<SearchSuggestions items={docs} query="chat" activeIndex={0} listboxId="lb" />)
    const option = screen.getAllByRole("option")[0]
    expect(option.tagName).toBe("A")
    expect(option).toHaveAttribute("href", "https://chat.openai.com")
    expect(document.getElementById(suggestionOptionId("lb", 0))).toBe(option)
  })

  it("未选中时提示「查看全部结果」，选中后变为「打开」", () => {
    const { rerender } = render(<SearchSuggestions items={docs} query="chat" activeIndex={-1} listboxId="lb" />)
    expect(screen.getByText("查看全部结果")).toBeInTheDocument()
    rerender(<SearchSuggestions items={docs} query="chat" activeIndex={0} listboxId="lb" />)
    expect(screen.getByText("打开")).toBeInTheDocument()
  })

  it("无建议时给出反馈与「查看全部结果」，而不是静默消失", () => {
    render(<SearchSuggestions items={[]} query="zzz" activeIndex={-1} listboxId="lb" />)
    expect(screen.getByRole("status")).toHaveTextContent("没有匹配建议")
    expect(screen.getByRole("button", { name: "查看全部结果" })).toBeInTheDocument()
  })

  it("建议请求未返回时显示加载态，不误报「没有匹配」", () => {
    render(<SearchSuggestions items={[]} query="zz" activeIndex={-1} listboxId="lb" settled={false} />)
    expect(screen.getByRole("status")).toHaveTextContent("正在搜索建议")
  })

  it("点「查看全部结果」触发回调", () => {
    const onViewAll = vi.fn()
    render(<SearchSuggestions items={docs} query="chat" activeIndex={-1} listboxId="lb" onViewAll={onViewAll} />)
    screen.getByRole("button", { name: "查看全部结果" }).click()
    expect(onViewAll).toHaveBeenCalledTimes(1)
  })
})
