import Link from "next/link"
import { ArrowRight } from "lucide-react"
import { Button } from "@/components/ui/button"
import { getStats } from "@/lib/data"

/**
 * 首页 Hero · 编辑筛选定位
 *
 * 一句话主张：不是又一个 AI 榜单，而是「替你筛过」的目录。
 * 版式保持单栏：标签 → 大标题 → 证据 → 双 CTA → 脚注；没有卡片、网格和分隔线。
 */
export function Hero() {
  const stats = getStats()

  return (
    <section id="hero" aria-labelledby="hero-title" className="bg-background px-4 pb-8 pt-10 sm:pb-10 sm:pt-12">
      <div className="hero-rise mx-auto flex max-w-4xl flex-col items-center text-center">
        <p className="inline-flex items-center gap-2 rounded-full border border-border/80 bg-background px-3.5 py-1.5 text-xs text-muted-foreground shadow-sm">
          <span className="size-1.5 rounded-full bg-foreground" aria-hidden />
          人工筛选 · 每周复核
        </p>

        <h1
          id="hero-title"
          className="mt-6 text-[2.25rem] font-semibold leading-[1.1] tracking-[-0.035em] text-balance sm:text-[3.5rem] sm:leading-[1.04] lg:text-[4rem]"
        >
          AI 工具，<span className="block sm:inline">替你筛过了。</span>
        </h1>

        <p className="mt-4 max-w-2xl text-[0.9375rem] leading-[1.65] text-muted-foreground sm:text-base">
          {stats.tools.toLocaleString("zh-CN")} 款在库，
          <strong className="font-semibold text-foreground">{stats.featured} 款精选</strong>。
          <span className="block sm:inline">按主题浏览，点开就是官网。</span>
        </p>

        <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
          <Button
            size="lg"
            className="h-10 px-5 text-sm shadow-sm transition-shadow hover:shadow-md"
            render={<Link href="/?tab=featured#tool-browser" prefetch={false} />}
          >
            先看 {stats.featured} 款精选
            <ArrowRight data-icon="inline-end" />
          </Button>
          <Button
            variant="outline"
            size="lg"
            className="h-10 bg-background px-5 text-sm"
            render={<Link href="/?tab=all#tool-browser" prefetch={false} />}
          >
            浏览全部工具
          </Button>
        </div>

        <p className="mt-3 font-data text-[0.6875rem] tracking-wide text-muted-foreground">
          {stats.topics} 个主题 · 无需注册 · 点开直达官网
        </p>
      </div>
    </section>
  )
}
