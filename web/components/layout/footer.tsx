import Link from "next/link"
import { pageShell } from "@/lib/layout"
import { Wordmark } from "@/components/brand/wordmark"
import { CopyrightYear } from "@/components/layout/copyright-year"
import pkg from "@/package.json"

const appVersion = pkg.version

export default function Footer() {
  return (
    <footer className="mt-12 border-t">
      <div
        className={pageShell(
          "browse",
          "flex flex-col gap-4 px-4 py-6 sm:flex-row sm:items-center sm:justify-between sm:px-6",
        )}
      >
        <Link
          href="/"
          aria-label="XiGee.net 首页"
          className="shrink-0 self-start rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Wordmark size="sm" />
        </Link>

        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground sm:justify-end">
          <nav aria-label="信息" className="flex items-center gap-3">
            <Link href="/about" prefetch={false} className="transition-colors hover:text-foreground">
              关于
            </Link>
            <Link href="/privacy" prefetch={false} className="transition-colors hover:text-foreground">
              隐私政策
            </Link>
            <Link href="/terms" prefetch={false} className="transition-colors hover:text-foreground">
              服务条款
            </Link>
          </nav>
          <span aria-hidden className="text-muted-foreground/40">
            ·
          </span>
          <span className="font-data text-muted-foreground/60">v{appVersion}</span>
          <span aria-hidden className="text-muted-foreground/40">
            ·
          </span>
          <span className="font-data text-muted-foreground/60">
            &copy; <CopyrightYear />
          </span>
        </div>
      </div>
    </footer>
  )
}
