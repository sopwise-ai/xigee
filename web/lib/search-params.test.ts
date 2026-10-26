import { describe, it, expect } from "vitest"
import { isSearchSort, readSearchState, SEARCH_SORT_OPTIONS } from "./search-params"

describe("readSearchState", () => {
  it("读取 q / sort", () => {
    expect(readSearchState(new URLSearchParams("?q=图像&sort=name"))).toEqual({
      query: "图像",
      sort: "name",
    })
  })

  it("缺省时给出空查询与相关度排序", () => {
    expect(readSearchState(new URLSearchParams(""))).toEqual({ query: "", sort: "relevance" })
  })

  it("非法 sort（含已下线的 latest）回退到 relevance", () => {
    expect(readSearchState(new URLSearchParams("?sort=whatever")).sort).toBe("relevance")
    expect(readSearchState(new URLSearchParams("?sort=latest")).sort).toBe("relevance")
  })

  it("接受任何只要 get 的对象（Next 的 ReadonlyURLSearchParams 也满足）", () => {
    const map = new Map([["q", "claude"]])
    expect(readSearchState({ get: (k: string) => map.get(k) ?? null }).query).toBe("claude")
  })
})

describe("isSearchSort", () => {
  it("只认声明过的排序值", () => {
    for (const option of SEARCH_SORT_OPTIONS) expect(isSearchSort(option.value)).toBe(true)
    expect(isSearchSort("bogus")).toBe(false)
    expect(isSearchSort(null)).toBe(false)
  })
})
