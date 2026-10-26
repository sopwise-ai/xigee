import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { SearchResults } from "./search-results"
import { mockTopics, mockTopicCounts, mockTools } from "@/.storybook/fixtures"
import { addRecentSearch } from "@/lib/recent-searches"

/** next/navigation 的可变替身：用例间切换 pathname / search。 */
const nav = vi.hoisted(() => ({ pathname: "/search", search: "" }))

vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useSearchParams: () => new URLSearchParams(nav.search),
}))

const featured = mockTools.filter((p) => p.featured)

function json(data: unknown) {
  return { ok: true, json: async () => data } as unknown as Response
}

function mockSearch() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://localhost")
    const q = url.searchParams.get("q") ?? ""
    if (q === "对话") {
      return json({
        items: [
          { ...mockTools[0], topicNames: [] },
          { ...mockTools[1], topicNames: [] },
        ],
        total: 2,
        hasMore: false,
        related: [],
      })
    }
    if (q === "代码") {
      return json({ items: [mockTools[4]], total: 1, hasMore: false, related: [] })
    }
    return json({ items: [], total: 0, hasMore: false, related: [] })
  })
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

function renderResults() {
  return render(<SearchResults featured={featured} topics={mockTopics} topicCounts={mockTopicCounts} />)
}

describe("SearchResults", () => {
  beforeEach(() => {
    localStorage.clear()
    nav.pathname = "/search"
    nav.search = ""
    window.history.replaceState(null, "", "/search")
    mockSearch()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("空查询走着陆态：给最近搜索/试试这些/主题出口，而不是一片空白", () => {
    renderResults()
    expect(screen.getByText("试试这些")).toBeInTheDocument()
    expect(screen.getByText("按主题浏览")).toBeInTheDocument()
    expect(screen.queryByText("最近搜索")).toBeNull()
    expect(document.querySelector("[data-search-result]")).toBeNull()
  })

  it("有最近搜索时在着陆态置顶展示（localStorage 只在客户端可得）", () => {
    addRecentSearch("图像生成")
    renderResults()
    expect(screen.getByText("最近搜索")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "图像生成" })).toBeInTheDocument()
  })

  it("带服务端首屏结果时直接渲染，不再发起 /api/search 请求", () => {
    nav.search = "?q=对话"
    const fetchMock = mockSearch()
    render(
      <SearchResults
        featured={featured}
        topics={mockTopics}
        topicCounts={mockTopicCounts}
        initial={{
          query: "对话",
          sort: "relevance",
          items: [
            { ...mockTools[0], topicNames: [] },
            { ...mockTools[1], topicNames: [] },
          ],
          total: 2,
          related: [],
        }}
      />,
    )

    expect(screen.getByRole("status")).toHaveTextContent("找到 2 个与「对话」相关的结果")
    expect(document.querySelectorAll("[data-search-result]")).toHaveLength(2)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("有结果时给出结果计数、排序入口与结果行", async () => {
    nav.search = "?q=对话"
    renderResults()

    expect(await screen.findByRole("status")).toHaveTextContent("找到 2 个与「对话」相关的结果")
    expect(screen.getByRole("button", { name: "排序" })).toBeInTheDocument()
    expect(document.querySelectorAll("[data-search-result]")).toHaveLength(2)
  })

  it("切换排序原地写 URL（replaceState，不发导航）", async () => {
    nav.search = "?q=对话"
    renderResults()
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("找到 2 个"))

    fireEvent.click(screen.getByRole("button", { name: "排序" }))
    fireEvent.click(await screen.findByRole("menuitemradio", { name: /最新/ }))
    expect(new URLSearchParams(window.location.search).get("sort")).toBe("latest")
  })

  it("未找到时走无结果页，并给出「也许你想找」/ 换词建议", async () => {
    nav.search = "?q=zzzznotfound"
    renderResults()

    expect(await screen.findByText(/未找到与/)).toBeInTheDocument()
    expect(screen.getByText("换个词试试：")).toBeInTheDocument()
    expect(document.querySelector("[data-search-result]")).toBeNull()
  })

  it("结果行带命中上下文（描述片段里能看到关键词）", async () => {
    nav.search = "?q=代码"
    renderResults()

    const row = await screen.findByText(/Copilot/)
    expect(row.closest("[data-search-result]")?.textContent).toContain("代码")
    expect(row.closest("[data-search-result]")?.querySelector("mark")).not.toBeNull()
  })
})
