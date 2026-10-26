import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { render, screen, fireEvent, act } from "@testing-library/react"
import { MainHeader } from "./main-header"
import { suggestionOptionId } from "@/components/search/search-suggestions"
import { mockTopics, mockSuggestionDocs } from "@/.storybook/fixtures"

/** next/navigation 的可变替身：用例间切换 pathname / search。 */
const nav = vi.hoisted(() => ({
  push: vi.fn(),
  prefetch: vi.fn(),
  pathname: "/",
  search: "",
}))

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: nav.push, prefetch: nav.prefetch, replace: vi.fn() }),
  usePathname: () => nav.pathname,
  useSearchParams: () => new URLSearchParams(nav.search),
}))

const DEBOUNCE_MS = 150

function renderHeader() {
  return render(<MainHeader topics={mockTopics} />)
}

function typeInto(value: string) {
  const input = screen.getByRole("combobox", { name: "搜索 AI 工具" }) as HTMLInputElement
  // 真实 focus：QuerySync 靠 document.activeElement 判断「用户正在打字」，只发事件不够
  act(() => {
    input.focus()
  })
  fireEvent.change(input, { target: { value } })
  return input
}

describe("MainHeader 面包屑", () => {
  beforeEach(() => {
    nav.pathname = "/"
    nav.search = ""
    window.history.replaceState(null, "", "/")
  })

  it("主题页面包屑第二段（当前页）是主题名", () => {
    nav.pathname = "/topic/chat-assistant"
    renderHeader()

    const crumb = screen.getByRole("navigation", { name: "面包屑" })
    expect(crumb.querySelector('[aria-current="page"]')?.textContent).toBe("对话助手")
  })

  it("未知主题 id 时只剩「全部工具」一段，不崩", () => {
    nav.pathname = "/topic/does-not-exist"
    renderHeader()

    const crumb = screen.getByRole("navigation", { name: "面包屑" })
    // 单段时它既是首项也是当前项，所以带 aria-current="page"
    expect(crumb.querySelector('[aria-current="page"]')?.textContent).toBe("全部工具")
    expect(crumb.textContent).not.toContain("does-not-exist")
  })

  it("面包屑不出现旧 /category/ 前缀", () => {
    nav.pathname = "/topic/chat-assistant"
    renderHeader()

    const crumb = screen.getByRole("navigation", { name: "面包屑" })
    expect(crumb.querySelector('a[href^="/category/"]')).toBeNull()
  })
})

describe("MainHeader 搜索", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    nav.pathname = "/"
    nav.search = ""
    window.history.replaceState(null, "", "/")
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => mockSuggestionDocs,
      }),
    )
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    window.history.replaceState(null, "", "/")
  })

  it("表单 action/method 与 input name：hydration 完成前回车走原生 GET 提交", () => {
    renderHeader()
    const form = screen.getByRole("search")
    expect(form).toHaveAttribute("action", "/search")
    expect(form).toHaveAttribute("method", "get")
    expect(screen.getByRole("combobox", { name: "搜索 AI 工具" })).toHaveAttribute("name", "q")
  })

  it("搜索页内边打边搜：原地写 URL，全程不发起客户端导航（旧版每次换词都要跑一趟服务器）", () => {
    vi.useFakeTimers()
    nav.pathname = "/search"
    window.history.replaceState(null, "", "/search")
    renderHeader()

    const input = typeInto("claude")
    expect(input).toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(DEBOUNCE_MS + 50)
    })

    expect(window.location.pathname).toBe("/search")
    expect(new URLSearchParams(window.location.search).get("q")).toBe("claude")
    expect(nav.push).not.toHaveBeenCalled()
  })

  it("回车立即定格 URL，不必等防抖", () => {
    vi.useFakeTimers()
    nav.pathname = "/search"
    window.history.replaceState(null, "", "/search")
    renderHeader()

    typeInto("图片生成")
    fireEvent.submit(screen.getByRole("search"))

    expect(new URLSearchParams(window.location.search).get("q")).toBe("图片生成")
    expect(nav.push).not.toHaveBeenCalled()
  })

  it("其它页面回车才做一次客户端跳转，并预取 /search", () => {
    renderHeader()

    typeInto("claude")
    fireEvent.submit(screen.getByRole("search"))

    expect(nav.push).toHaveBeenCalledWith("/search?q=claude")
    expect(nav.prefetch).toHaveBeenCalledWith("/search")
    // 非搜索页不改当前地址栏
    expect(window.location.search).toBe("")
  })

  it("回车提交后立即收起建议浮层（回归：进 /search 后浮层仍遮挡排序与结果）", async () => {
    renderHeader()

    const input = typeInto("chat")
    expect(await screen.findByRole("listbox", { name: "搜索建议" })).toBeInTheDocument()
    expect(input).toHaveAttribute("aria-expanded", "true")

    fireEvent.submit(screen.getByRole("search"))

    expect(screen.queryByRole("listbox")).toBeNull()
    expect(input).toHaveAttribute("aria-expanded", "false")
    // 收起浮层不等于丢输入：跳转 URL 仍然带着 q
    expect(nav.push).toHaveBeenCalledWith("/search?q=chat")
  })

  it("其它页输入后按查询请求建议，↑↓ 即可选中", async () => {
    renderHeader()

    const input = typeInto("chat")
    const listbox = await screen.findByRole("listbox", { name: "搜索建议" })
    expect(listbox).toBeInTheDocument()
    expect(input).toHaveAttribute("aria-expanded", "true")

    fireEvent.keyDown(input, { key: "ArrowDown" })
    expect(input).toHaveAttribute("aria-activedescendant", suggestionOptionId("search-suggestions", 0))
    expect(document.getElementById(suggestionOptionId("search-suggestions", 0))).toHaveAttribute(
      "aria-selected",
      "true",
    )

    // 从第一条再往上 = 回绕到最后一条（不是回到「未选中」）
    const count = screen.getAllByRole("option").length
    fireEvent.keyDown(input, { key: "ArrowUp" })
    expect(input).toHaveAttribute("aria-activedescendant", suggestionOptionId("search-suggestions", count - 1))
  })

  it("选中建议后回车会真正打开该工具（回归：id 曾挂在 <li> 上导致点击落空）", async () => {
    renderHeader()

    const input = typeInto("chat")
    await screen.findByRole("listbox", { name: "搜索建议" })
    fireEvent.keyDown(input, { key: "ArrowDown" })

    const activeId = input.getAttribute("aria-activedescendant")
    expect(activeId).toBeTruthy()
    const option = document.getElementById(activeId as string)
    // 关键断言：激活项必须本身就是链接，否则 `.click()` 点不到任何可导航的元素
    expect(option?.tagName).toBe("A")

    const onClicked = vi.fn()
    option?.addEventListener("click", onClicked)
    fireEvent.keyDown(input, { key: "Enter" })
    expect(onClicked).toHaveBeenCalledTimes(1)
  })

  it("搜索页不弹建议下拉（结果页下方已经实时出结果，两份列表是重复的）", () => {
    vi.useFakeTimers()
    nav.pathname = "/search"
    window.history.replaceState(null, "", "/search")
    renderHeader()

    typeInto("chat")
    expect(screen.queryByRole("listbox")).toBeNull()
  })

  it("Esc 先收下拉并保留已输入内容，再按一次才清空", async () => {
    renderHeader()

    const input = typeInto("chat") as HTMLInputElement
    expect(await screen.findByRole("listbox")).toBeInTheDocument()

    fireEvent.keyDown(input, { key: "Escape" })
    expect(screen.queryByRole("listbox")).toBeNull()
    expect(input.value).toBe("chat")

    fireEvent.keyDown(input, { key: "Escape" })
    expect(input.value).toBe("")
  })
})
