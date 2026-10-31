"use client"

import { Search } from "lucide-react"
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from "@/components/ui/input-group"
import { MAX_SEARCH_QUERY_LENGTH } from "@/lib/search-limits"
import type { SearchSort } from "@/lib/search-params"

interface SearchPageInputProps {
  query: string
  sort: SearchSort
}

/**
 * 搜索页自己的输入框（移动端）。
 *
 * 桌面端顶栏始终有搜索框；移动端顶栏收起成图标，进结果页后改词必须再点一次图标 ——
 * 这里补一个常驻输入框，表单走原生 GET，hydration 前也能提交。
 */
export function SearchPageInput({ query, sort }: SearchPageInputProps) {
  return (
    <form action="/search" method="get" role="search" aria-label="搜索工具" className="w-full">
      {sort !== "relevance" && <input type="hidden" name="sort" value={sort} />}
      <InputGroup className="h-10">
        <InputGroupAddon align="inline-start">
          <Search className="text-muted-foreground" aria-hidden />
        </InputGroupAddon>
        <InputGroupInput
          key={query}
          name="q"
          type="search"
          defaultValue={query}
          maxLength={MAX_SEARCH_QUERY_LENGTH}
          enterKeyHint="search"
          autoComplete="off"
          aria-label="搜索 AI 工具"
          placeholder="搜索 AI 工具…"
        />
        <InputGroupAddon align="inline-end">
          <InputGroupButton type="submit" variant="secondary" size="sm" className="h-7 px-2.5">
            搜索
          </InputGroupButton>
        </InputGroupAddon>
      </InputGroup>
    </form>
  )
}
