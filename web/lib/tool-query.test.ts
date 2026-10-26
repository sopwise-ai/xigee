import { describe, it, expect } from "vitest"
import { isValidSort, isValidView, readUrlParams, resolveInitialTab } from "./tool-query"

describe("readUrlParams", () => {
  it("空查询返回全 null", () => {
    expect(readUrlParams("")).toEqual({ tab: null, view: null, sort: null })
  })

  it("解析合法 tab/view/sort", () => {
    expect(readUrlParams("?tab=featured&view=list&sort=name-asc")).toEqual({
      tab: "featured",
      view: "list",
      sort: "name-asc",
    })
  })

  it("兼容旧版 filter 别名：featured → featured，latest → all", () => {
    expect(readUrlParams("?filter=featured").tab).toBe("featured")
    expect(readUrlParams("?filter=latest").tab).toBe("all")
  })

  it("tab 优先于 filter 别名", () => {
    expect(readUrlParams("?tab=latest&filter=featured").tab).toBe("featured")
  })

  it("非法值归一化为 null", () => {
    expect(readUrlParams("?tab=bogus&view=bogus&sort=bogus")).toEqual({
      tab: null,
      view: null,
      sort: null,
    })
  })

  it("filter 命中 Object.prototype 属性时归一化为 null（不走原型链）", () => {
    expect(readUrlParams("?filter=constructor").tab).toBeNull()
    expect(readUrlParams("?filter=toString").tab).toBeNull()
    expect(readUrlParams("?filter=__proto__").tab).toBeNull()
    expect(readUrlParams("?filter=hasOwnProperty").tab).toBeNull()
  })
})

describe("isValidView / isValidSort", () => {
  it("识别合法展示偏好", () => {
    expect(isValidView("grid")).toBe(true)
    expect(isValidView("list")).toBe(true)
    expect(isValidView("bogus")).toBe(false)
    expect(isValidSort("latest")).toBe(false)
    expect(isValidSort("name-desc")).toBe(true)
    expect(isValidSort("bogus")).toBe(false)
  })
})

describe("resolveInitialTab", () => {
  const base = { urlTab: null, storedTab: null, defaultTab: "all", showTabs: true } as const

  it("展示 Tab 的页面：URL > 本地偏好 > 默认", () => {
    expect(resolveInitialTab({ ...base, urlTab: "featured" })).toBe("featured")
    expect(resolveInitialTab({ ...base, storedTab: "featured" })).toBe("featured")
    expect(resolveInitialTab({ ...base })).toBe("all")
    expect(resolveInitialTab({ ...base, urlTab: "featured", storedTab: "featured" })).toBe("featured")
  })

  it("不展示 Tab 的页面（主题页）：忽略 URL 与本地偏好，恒为默认", () => {
    expect(resolveInitialTab({ ...base, showTabs: false, urlTab: "featured" })).toBe("all")
    expect(resolveInitialTab({ ...base, showTabs: false, storedTab: "featured" })).toBe("all")
    expect(resolveInitialTab({ ...base, showTabs: false, urlTab: "featured", storedTab: "featured" })).toBe("all")
    expect(resolveInitialTab({ ...base, showTabs: false, defaultTab: "featured" })).toBe("featured")
  })
})
