import type { Pricing } from "@/lib/types"
import { cn } from "@/lib/utils"

export interface PricingStyle {
  label: string
  className: string
  dotClass: string
}

/** 价格 → 状态徽章（语义色：免费绿 / 免费增值蓝 / 付费琥珀 / 开源紫） */
export const pricingStyles: Record<Pricing, PricingStyle> = {
  free: {
    label: "免费",
    className: "bg-price-free/10 text-price-free border-price-free/20",
    dotClass: "bg-price-free",
  },
  freemium: {
    label: "免费增值",
    className: "bg-price-freemium/10 text-price-freemium border-price-freemium/20",
    dotClass: "bg-price-freemium",
  },
  paid: {
    label: "付费",
    className: "bg-price-paid/10 text-price-paid border-price-paid/20",
    dotClass: "bg-price-paid",
  },
  opensource: {
    label: "开源",
    className: "bg-price-opensource/10 text-price-opensource border-price-opensource/20",
    dotClass: "bg-price-opensource",
  },
}

export function PricingBadge({ pricing }: { pricing: Pricing }) {
  const style = pricingStyles[pricing]
  return (
    <span
      data-slot="pricing-badge"
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-xs font-medium tracking-wide",
        style.className,
      )}
    >
      <span className={cn("size-1.5 rounded-full", style.dotClass)} aria-hidden />
      {style.label}
    </span>
  )
}
