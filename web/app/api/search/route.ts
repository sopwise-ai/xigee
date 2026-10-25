import { NextResponse } from "next/server"
import { searchTools } from "@/lib/catalog"
import { isSearchSort } from "@/lib/search-params"

const DEFAULT_PAGE_SIZE = 50
const MAX_PAGE_SIZE = 100

/** 服务端搜索：客户端只拿当前页结果，不再下载全量工具并本地建 Fuse 索引。 */
export async function GET(request: Request) {
  const params = new URL(request.url).searchParams
  const query = params.get("q") ?? ""
  const sort = params.get("sort")
  const page = Number(params.get("page") ?? "1")
  const pageSize = Number(params.get("pageSize") ?? DEFAULT_PAGE_SIZE)

  const result = searchTools({
    query,
    sort: isSearchSort(sort) ? sort : "relevance",
    page: Number.isFinite(page) ? page : 1,
    pageSize: Number.isFinite(pageSize) ? Math.min(MAX_PAGE_SIZE, pageSize) : DEFAULT_PAGE_SIZE,
  })

  return NextResponse.json(result, {
    headers: { "Cache-Control": "public, s-maxage=300, stale-while-revalidate=3600" },
  })
}
