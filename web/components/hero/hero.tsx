import Link from "next/link"
import { ArrowRight, Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import { getStats } from "@/lib/data"
import { formatCount } from "@/lib/format"

/**
 * 首页 Hero · 纯排版落地页（参考 YC 式单栏）
 *
 * 没有卡片、网格、渐变边框和分隔线：只有一枚小标签、一句大标题、两行说明、两个 CTA
 * 和一行统计。留白承担层级，工具列表紧接在下面。
 * Server Component，纯 CSS，零客户端 JS。
 */
export function Hero() {
  const stats = getStats()

  return (
    <section id="hero" aria-labelledby="hero-title" className="bg-background px-4 pb-10 pt-12 sm:pb-14 sm:pt-16">
      <div className="hero-rise mx-auto flex max-w-4xl flex-col items-center text-center">
        <p className="inline-flex items-center gap-2 rounded-full border border-border/80 bg-background px-3.5 py-1.5 text-xs text-muted-foreground shadow-sm">
          <span className="size-1.5 rounded-full bg-foreground" aria-hidden />
          人工筛选 · 每周更新
        </p>

        <h1
          id="hero-title"
          className="mt-7 text-[2.5rem] font-semibold leading-[1.08] tracking-[-0.035em] text-balance sm:text-[4rem] sm:leading-[1.02] lg:text-[4.5rem]"
        >
          发现值得用的
          <span className="block sm:inline"> AI 工具</span>
        </h1>

        <p className="mt-5 max-w-2xl text-[0.9375rem] leading-[1.7] text-muted-foreground sm:text-lg">
          从 {formatCount(stats.tools)} 款工具里筛掉噪音。
          <strong className="block font-semibold text-foreground sm:inline">只留下真正值得用的。</strong>
        </p>

        <div className="mt-7 flex flex-wrap items-center justify-center gap-3">
          <Button
            size="lg"
            className="h-11 px-5 text-sm shadow-sm transition-shadow hover:shadow-md"
            render={<Link href="/?tab=all#tool-browser" prefetch={false} />}
          >
            浏览全部工具
            <ArrowRight data-icon="inline-end" />
          </Button>
          <Button
            variant="outline"
            size="lg"
            className="h-11 bg-background px-5 text-sm"
            render={<Link href="/?tab=featured#tool-browser" prefetch={false} />}
          >
            <Sparkles data-icon="inline-start" className="text-muted-foreground" />
            探索精选
          </Button>
        </div>

        <p className="mt-4 font-data text-[0.6875rem] tracking-wide text-muted-foreground">
          {formatCount(stats.tools)} 款工具 · {stats.topics} 个主题 · {formatCount(stats.featured)} 个精选
        </p>
      </div>
    </section>
  )
}
