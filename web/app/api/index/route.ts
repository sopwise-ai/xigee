export const preferredRegion = "sin1"

import { NextResponse } from "next/server"
import { getAllTools, getToolsByTopic } from "@/lib/data"
import { encodeToolIndex, toToolIndex } from "@/lib/tool"

/**
 * 轻量索引（id/name/featured/date）外置为可缓存接口。
 *
 * 之前整份索引随首页/主题页进入 RSC 与 HTML（约 470 KB），是首屏 1 MB 的主要来源；
 * 现在 HTML 只带首屏工具，索引在 hydration 后按需拉取并走 CDN 缓存。
 * topic 参数让主题页只取本主题的索引，避免 49 个主题页都下载全量。
 */
export async function GET(request: Request) {
  const topic = new URL(request.url).searchParams.get("topic")
  const tools = topic ? getToolsByTopic(topic) : getAllTools()
  const index = encodeToolIndex(tools.map(toToolIndex))

  return NextResponse.json(index, {
    headers: { "Cache-Control": "public, s-maxage=3600, stale-while-revalidate=86400" },
  })
}
