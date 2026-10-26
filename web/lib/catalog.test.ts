import { describe, expect, it } from "vitest"
import { getToolsByIds, searchTools, suggestTools } from "./catalog"

describe("catalog", () => {
  it("按 id 取完整工具，保持请求顺序并忽略未知 id", () => {
    const tools = getToolsByIds(["chatgpt", "not-a-real-tool", "opencode"])
    expect(tools.map((tool) => tool.name)).toEqual(["ChatGPT", "OpenCode"])
    expect(tools[0].description).toBeTruthy()
    expect(tools[0].url).toMatch(/^https:\/\//)
  })

  it("服务端搜索返回分页结果与总数", () => {
    const page = searchTools({ query: "open", sort: "relevance", page: 1, pageSize: 5 })
    expect(page.total).toBeGreaterThan(0)
    expect(page.items.length).toBe(Math.min(5, page.total))
    expect(page.hasMore).toBe(page.total > 5)
  })

  it("长 query 的无结果不再触发高成本 fallback", () => {
    const page = searchTools({
      query: "z".repeat(32),
      sort: "relevance",
      page: 1,
      pageSize: 5,
    })
    expect(page.total).toBe(0)
    expect(page.related).toEqual([])
  })

  it("facets 在命中集合上过滤，并按过滤后总数分页", () => {
    const page = searchTools({ query: "翻译", sort: "relevance", page: 1, pageSize: 100, topic: "translation" })
    expect(page.total).toBeGreaterThan(0)
    expect(page.items.every((item) => item.topics.includes("translation"))).toBe(true)
  })

  it("空建议查询直接返回空数组", () => {
    expect(suggestTools("   ")).toEqual([])
  })

  it("建议最多返回 6 条并包含名称", () => {
    const items = suggestTools("open", 6)
    expect(items.length).toBeGreaterThan(0)
    expect(items.length).toBeLessThanOrEqual(6)
    expect(items.every((item) => item.name.length > 0)).toBe(true)
  })
})
