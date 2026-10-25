import { NextResponse } from "next/server"
import { suggestTools } from "@/lib/catalog"

const LIMIT = 6

/** 顶栏建议：按查询返回前 6 条，替代每个页面都下发 6000+ 条建议索引。 */
export async function GET(request: Request) {
  const query = new URL(request.url).searchParams.get("q") ?? ""
  return NextResponse.json(suggestTools(query, LIMIT), {
    headers: { "Cache-Control": "public, s-maxage=300, stale-while-revalidate=3600" },
  })
}
