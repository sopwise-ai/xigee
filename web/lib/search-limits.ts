/** 服务端 Fuse 查询上限：防止超长 query 把单次搜索放大成秒级 CPU。 */
export const MAX_SEARCH_QUERY_LENGTH = 32

/** 顶栏建议只需要短词，限制更严。 */
export const MAX_SUGGEST_QUERY_LENGTH = 24

/** 「也许相关」只对短查询执行：长 query 的 fallback 搜索成本远高于正常搜索。 */
export const MAX_FALLBACK_QUERY_LENGTH = 12
