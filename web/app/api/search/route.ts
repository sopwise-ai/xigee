import { NextResponse } from "next/server"
import { searchTools } from "@/lib/catalog"
import { SEARCH_PRICING_OPTIONS } from "@/lib/search-params"
import type { Pricing } from "@/lib/types"

const DEFAULT_PAGE_SIZE = 50
const MAX_PAGE_SIZE = 100

/** 服务端搜索：客户端只拿当前页结果，不再下载全量工具并本地建 Fuse 索引。 */
export async function GET(request: Request) {
  const params = new URL(request.url).searchParams
  const query = params.get("q") ?? ""
  const sort = params.get("sort")
  const page = Number(params.get("page") ?? "1")
  const pageSize = Number(params.get("pageSize") ?? DEFAULT_PAGE_SIZE)

  const pricing = params.get("pricing") ?? ""
  const validPricing = SEARCH_PRICING_OPTIONS.some((option) => option.value === pricing)
    ? (pricing as Pricing)
    : undefined

  const result = searchTools({
    query,
    sort: sort === "latest" || sort === "name" ? sort : "relevance",
    page: Number.isFinite(page) ? page : 1,
    pageSize: Number.isFinite(pageSize) ? Math.min(MAX_PAGE_SIZE, pageSize) : DEFAULT_PAGE_SIZE,
    topic: params.get("topic") || undefined,
    pricing: validPricing,
    featured: params.get("featured") === "1",
  })

  return NextResponse.json(result, {
    headers: { "Cache-Control": "public, s-maxage=300, stale-while-revalidate=3600" },
  })
}
