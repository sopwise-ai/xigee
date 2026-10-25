import { NextResponse } from "next/server"
import { getToolsByIds } from "@/lib/catalog"

const MAX_IDS = 100

/**
 * 按 id 批量取完整工具（列表分页用）。
 *
 * 客户端只持有轻量索引；当前页需要的描述/标签/价格/URL 由这里补齐，
 * 避免全量工具（约 2 MB）进入首屏 RSC payload。
 */
export async function GET(request: Request) {
  const raw = new URL(request.url).searchParams.get("ids") ?? ""
  const ids = raw
    .split(",")
    .map((id) => id.trim())
    .filter(Boolean)

  if (ids.length === 0) return NextResponse.json([])
  if (ids.length > MAX_IDS) {
    return NextResponse.json({ detail: `ids 最多 ${MAX_IDS} 个` }, { status: 400 })
  }

  return NextResponse.json(getToolsByIds(ids), {
    headers: { "Cache-Control": "public, s-maxage=3600, stale-while-revalidate=86400" },
  })
}
