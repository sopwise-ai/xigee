import "server-only"

import { getAllTools, getAllTopics } from "./data"
import {
  buildSearchDocs,
  buildSuggestionDocs,
  createFallbackIndex,
  createSearchIndex,
  findRelated,
  getSuggestionIndex,
  suggest,
  type SearchDoc,
  type SuggestionDoc,
} from "./search"
import type { SearchSort } from "./search-params"
import { compareDateDesc, compareName, getToolDate } from "./tool"
import type { Tool } from "./types"

const tools = getAllTools()
const topics = getAllTopics()
const toolById = new Map(tools.map((tool) => [tool.id, tool]))
const topicNames = Object.fromEntries(topics.map((topic) => [topic.id, topic.name]))

const searchDocs = buildSearchDocs(tools, topicNames)
const searchIndex = createSearchIndex(searchDocs)
const fallbackIndex = createFallbackIndex(searchDocs)
const suggestionDocs = buildSuggestionDocs(tools, topicNames)
const suggestionIndex = getSuggestionIndex(suggestionDocs)

export interface ToolSearchPage {
  items: SearchDoc[]
  total: number
  hasMore: boolean
  /** 仅在没有任何结果时返回：放宽阈值的「也许相关」。 */
  related: SearchDoc[]
}

/** 按 id 批量取完整工具；保持请求顺序，未知 id 静默忽略。 */
export function getToolsByIds(ids: readonly string[]): Tool[] {
  const result: Tool[] = []
  for (const id of ids) {
    const tool = toolById.get(id)
    if (tool) result.push(tool)
  }
  return result
}

/** 服务端搜索：分页、排序与「也许相关」都在这里完成，客户端不再持有全量工具。 */
export function searchTools(input: {
  query: string
  sort: SearchSort
  page: number
  pageSize: number
}): ToolSearchPage {
  const query = input.query.trim()
  if (!query) return { items: [], total: 0, hasMore: false, related: [] }

  const page = Math.max(1, Math.floor(input.page) || 1)
  const pageSize = Math.min(100, Math.max(1, Math.floor(input.pageSize) || 50))
  const items = searchIndex.search(query).map((result) => result.item)

  if (input.sort === "latest") {
    items.sort((a, b) => compareDateDesc(getToolDate(a), getToolDate(b)) || compareName(a, b))
  } else if (input.sort === "name") {
    items.sort(compareName)
  }

  const total = items.length
  const start = (page - 1) * pageSize
  const pageItems = items.slice(start, start + pageSize)
  const related = total === 0 && page === 1 ? findRelated(fallbackIndex, query, 6) : []

  return {
    items: pageItems,
    total,
    hasMore: start + pageItems.length < total,
    related,
  }
}

/** 顶栏建议：只返回当前查询的前 N 条，避免把全量建议索引下发到每个页面。 */
export function suggestTools(query: string, limit = 6): SuggestionDoc[] {
  return suggest(suggestionIndex, query, limit)
}
