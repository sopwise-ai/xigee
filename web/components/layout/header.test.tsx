import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import Header from "./header"

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: () => {}, replace: () => {} }),
  usePathname: () => "/",
}))

/** 模拟视口宽度查询：仅覆盖 (min-width: 768px)。 */
function installViewport(isDesktop: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: query.includes("min-width") ? isDesktop : false,
      media: query,
      onchange: null,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
      dispatchEvent: () => false,
    })),
  )
}

describe("移动端 Header 搜索快捷键", () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => vi.unstubAllGlobals())

  it("移动端视口按 / 应展开搜索框并聚焦", () => {
    installViewport(false)
    render(<Header className="md:hidden" />)
    expect(screen.queryByRole("combobox", { name: "搜索 AI 工具" })).toBeNull()
    fireEvent.keyDown(window, { key: "/" })
    const input = screen.getByRole("combobox", { name: "搜索 AI 工具" })
    expect(input).toBeTruthy()
    expect(document.activeElement).toBe(input)
  })

  it("桌面视口不应由移动 Header 处理 /（避免与 MainHeader 重复）", () => {
    installViewport(true)
    render(<Header className="md:hidden" />)
    fireEvent.keyDown(window, { key: "/" })
    expect(screen.queryByRole("combobox", { name: "搜索 AI 工具" })).toBeNull()
  })

  it("输入框中按 / 不应触发（避免吞键）", () => {
    installViewport(false)
    render(<Header className="md:hidden" />)
    const btn = screen.getByRole("button", { name: "搜索工具" })
    fireEvent.click(btn)
    const input = screen.getByRole("combobox", { name: "搜索 AI 工具" })
    input.focus()
    fireEvent.keyDown(input, { key: "/" })
    // 输入框仍存在（未重复触发），且焦点仍在输入框
    expect(document.activeElement).toBe(input)
  })
})
