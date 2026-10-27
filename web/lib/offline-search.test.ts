import { describe, expect, it, vi } from "vitest"
import { searchOffline } from "./offline-search"
import type { ToolIndexPayload } from "./tool"

const payload: ToolIndexPayload = {
  ids: ["chatgpt", "midjourney"],
  names: ["ChatGPT", "Midjourney"],
  urls: ["https://chat.openai.com", "https://midjourney.com"],
  featured: [0],
}

describe("searchOffline", () => {
  it("按名称过滤缓存索引，并带上可打开的 url", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => payload }))
    const result = await searchOffline("chat")
    expect(result.total).toBe(1)
    expect(result.items[0]).toMatchObject({ id: "chatgpt", url: "https://chat.openai.com" })
    vi.unstubAllGlobals()
  })

  it("空查询不发请求", async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)
    expect(await searchOffline("   ")).toEqual({ items: [], total: 0 })
    expect(fetchMock).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })
})
