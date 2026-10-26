import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { render, act, screen, fireEvent, waitFor } from "@testing-library/react"
import { ToolBrowser } from "./tool-browser"
import { toToolIndex } from "@/lib/tool"
import type { Tool } from "@/lib/types"

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
  useRouter: () => ({ push: () => {}, replace: () => {} }),
  usePathname: () => "/",
}))

function makeTool(id: string): Tool {
  return {
    id,
    name: `Tool ${id}`,
    description: "desc",
    url: `https://${id}.example.com`,
    topics: ["test"],
    pricing: "free",
    createdAt: "2024-01-01",
  }
}

const tools = [makeTool("a"), makeTool("b")]
const index = tools.map(toToolIndex)

describe("ToolBrowser a11y ids", () => {
  beforeEach(() => localStorage.clear())

  it("tab 与 tabpanel 的 id/aria 关联正确（单实例）", () => {
    const { container } = render(<ToolBrowser index={index} initialTools={tools} />)
    const tabs = container.querySelectorAll<HTMLElement>('[role="tab"]')
    const panel = container.querySelector<HTMLElement>('[role="tabpanel"]')
    expect(tabs.length).toBe(2)
    expect(panel).not.toBeNull()
    for (const tab of tabs) {
      expect(tab.getAttribute("aria-controls")).toBe(panel!.id)
    }
    // 有且仅有一个 tab 处于选中态
    const selected = container.querySelectorAll('[role="tab"][aria-selected="true"]')
    expect(selected.length).toBe(1)
  })

  it("同页两个实例的 tabpanel id 不重复（aria 关联不被串扰）", () => {
    const { container } = render(
      <>
        <ToolBrowser index={index} initialTools={tools} showTabs />
        <ToolBrowser index={index} initialTools={tools} showTabs />
      </>,
    )
    const panels = container.querySelectorAll<HTMLElement>('[role="tabpanel"]')
    expect(panels.length).toBe(2)
    expect(panels[0].id).not.toBe(panels[1].id)
    // 每个实例的 tab 都应指向自己那一侧的 panel
    const allTabs = [...container.querySelectorAll<HTMLElement>('[role="tab"]')]
    expect(allTabs.filter((t) => t.getAttribute("aria-controls") === panels[0].id).length).toBe(2)
    expect(allTabs.filter((t) => t.getAttribute("aria-controls") === panels[1].id).length).toBe(2)
  })
})

describe("ToolBrowser URL sort 同步", () => {
  beforeEach(() => {
    localStorage.clear()
    window.history.replaceState(null, "", "/")
  })

  it("latest tab 不应把隐式排序写入 URL（避免污染 sort 状态）", () => {
    window.history.replaceState(null, "", "/?tab=latest")
    render(<ToolBrowser index={index} initialTools={tools} />)
    expect(new URLSearchParams(window.location.search).get("sort")).toBeNull()
  })

  it("从 latest tab 切到全部后，不应残留 sort=latest", () => {
    window.history.replaceState(null, "", "/?tab=latest")
    render(<ToolBrowser index={index} initialTools={tools} />)
    act(() => {
      fireEvent.click(screen.getByRole("tab", { name: "全部" }))
    })
    expect(new URLSearchParams(window.location.search).get("sort")).toBeNull()
  })
})

describe("ToolBrowser 无 Tab 页面", () => {
  beforeEach(() => {
    localStorage.clear()
    window.history.replaceState(null, "", "/")
  })

  it("showTabs=false 时忽略 URL 的 tab，不静默过滤工具", () => {
    // 工具 b 为精选；?tab=featured 若生效会导致只显示 b
    const withFeatured = [makeTool("a"), { ...makeTool("b"), featured: true }]
    window.history.replaceState(null, "", "/?tab=featured")
    render(<ToolBrowser index={withFeatured.map(toToolIndex)} initialTools={withFeatured} showTabs={false} />)
    // 两个工具都应显示（tab 被忽略），且 URL 上的 tab 被清理
    expect(screen.getAllByText(/Tool [ab]/).length).toBe(2)
    expect(new URLSearchParams(window.location.search).get("tab")).toBeNull()
  })
})

describe("ToolBrowser 分页加载", () => {
  beforeEach(() => {
    localStorage.clear()
    window.history.replaceState(null, "", "/")
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("未注入索引时先渲染 server 首屏，索引到达后再出现分页", async () => {
    const many = ["a", "b", "c", "d", "e"].map(makeTool)
    const first = many.slice(0, 2)
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).startsWith("/api/index")) {
          return { ok: true, json: async () => many.map(toToolIndex) } as unknown as Response
        }
        return { ok: true, json: async () => [] } as unknown as Response
      }),
    )

    render(<ToolBrowser initialTools={first} pageSize={2} />)
    expect(screen.getAllByText(/Tool [a-e]/)).toHaveLength(2)
    await waitFor(() => expect(screen.getByRole("navigation", { name: "列表分页" })).toHaveTextContent("第 1 / 3 页"))
  })

  it("首屏只渲染 pageSize 条，翻页时按 id 补齐完整工具", async () => {
    const many = ["a", "b", "c", "d", "e"].map(makeTool)
    const first = many.slice(0, 2)
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => many.slice(2, 4),
    })
    vi.stubGlobal("fetch", fetchMock)

    render(<ToolBrowser index={many.map(toToolIndex)} initialTools={first} pageSize={2} />)

    expect(screen.getAllByText(/Tool [a-e]/)).toHaveLength(2)
    fireEvent.click(screen.getByRole("button", { name: /下一页/ }))

    await waitFor(() => expect(screen.getByText("Tool c")).toBeInTheDocument())
    expect(screen.getByText("Tool d")).toBeInTheDocument()
    expect(screen.queryByText("Tool a")).toBeNull()
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/tools?ids=c%2Cd",
      expect.objectContaining({ signal: expect.anything() }),
    )
  })
})
