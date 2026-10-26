import type { SearchDoc } from "./search"
import type { ToolIndexPayload } from "./tool"

/**
 * 离线搜索兜底：Service Worker 缓存了 `/api/index`，断网时按名称做一次本地过滤。
 *
 * 只匹配名称（索引里没有描述/标签），结果页会明确标注「离线模式」；上限 100 条，
 * 避免一次性把几千个 DOM 节点塞进离线页面。
 */
export async function searchOffline(query: string, limit = 100): Promise<{ items: SearchDoc[]; total: number }> {
  const trimmed = query.trim().toLowerCase()
  if (!trimmed) return { items: [], total: 0 }

  const response = await fetch("/api/index")
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  const payload = (await response.json()) as ToolIndexPayload | SearchDoc[]
  const docs: SearchDoc[] = Array.isArray(payload)
    ? payload
    : payload.ids.map((id, i) => ({
        id,
        name: payload.names[i] ?? "",
        description: "离线模式：仅按名称匹配",
        url: payload.urls?.[i] ?? "",
        topics: [],
        topicNames: [],
      }))

  const hits = docs
    .filter((doc) => doc.name.toLowerCase().includes(trimmed))
    .sort((a, b) => a.name.localeCompare(b.name, "zh-CN"))
  return { items: hits.slice(0, limit), total: Math.min(hits.length, limit) }
}
