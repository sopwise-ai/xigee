import Link from "next/link"
import { ArrowRight, Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { HeroBackdrop, HeroEyebrow } from "@/components/hero/hero-primitives"
import { HeroStatsBar } from "@/components/hero/hero-stats-bar"
import { getStats } from "@/lib/data"

/**
 * 首页 Hero · 编辑精选（A 方案）
 *
 * 排版主导的克制高级感：品牌字体大标题 + 一句价值主张 + 双 CTA + 实时统计，
 * 靠留白、细网格与顶部微光建立纵深，而非重卡片。紧凑（桌面 ≈230px / 移动 ≈250px），把首屏还给工具列表。
 * Server Component，纯 CSS，无客户端 JS → 零 FOUC / 零 CLS。
 */
export function Hero() {
  const stats = getStats()

  return (
    <section
      id="hero"
      aria-labelledby="hero-title"
      className="relative overflow-hidden rounded-2xl border border-border/70 bg-gradient-to-b from-secondary/50 to-background px-5 py-4 sm:px-8 sm:py-5"
    >
      <HeroBackdrop align="left" />

      <div className="hero-rise relative max-w-2xl">
        <HeroEyebrow>Curated AI Directory</HeroEyebrow>

        {/* 视觉大标题即页面 h1（原来 h1 藏在 sr-only、视觉标题用 h2，屏幕阅读器与视觉各说一套）；
            工具卡片相应为 h2，层级 h1 → h2 连续不跨级 */}
        <h1
          id="hero-title"
          className="mt-3 font-brand text-[1.75rem] font-semibold leading-[1.08] tracking-[-0.012em] text-balance sm:text-[2.125rem]"
        >
          <span className="bg-gradient-to-r from-foreground via-foreground/90 to-foreground/85 bg-clip-text text-transparent">
            发现值得用的 AI 工具
          </span>
        </h1>

        <p className="mt-2 max-w-xl text-[0.8125rem] leading-[1.6] text-muted-foreground sm:text-sm">
          精选值得用的 AI 工具，每一款都经过人工筛选——按主题浏览，或直接搜索。
        </p>

        <div className="mt-3 flex flex-wrap items-center gap-2.5">
          <Button
            size="lg"
            className="shadow-sm transition-shadow hover:shadow-md"
            render={<Link href="/?tab=all#tool-browser" prefetch={false} />}
          >
            浏览全部工具
            <ArrowRight data-icon="inline-end" />
          </Button>
          <Button variant="outline" size="lg" render={<Link href="/?tab=featured#tool-browser" prefetch={false} />}>
            <Sparkles data-icon="inline-start" className="text-muted-foreground" />
            探索精选
          </Button>
        </div>

        <Separator className="mt-4" />
        <HeroStatsBar stats={stats} className="pt-3" />
      </div>
    </section>
  )
}
