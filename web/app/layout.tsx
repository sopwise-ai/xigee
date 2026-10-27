import type { Metadata, Viewport } from "next"
import localFont from "next/font/local"
import { getAllTopics, getTopicCounts, getStats } from "@/lib/data"
import { getBaseUrl } from "@/lib/utils"
import { pageShell } from "@/lib/layout"
import { BRAND_PAGE } from "@/lib/brand"
import { STORAGE_PREFIX } from "@/lib/storage"
import Header from "@/components/layout/header"
import { SubNav } from "@/components/layout/sub-nav"
import { Sidebar } from "@/components/layout/sidebar"
import { MainHeader } from "@/components/layout/main-header"
import { HistoryTracker } from "@/components/runtime/history-tracker"
import { PwaRegister } from "@/components/runtime/pwa-register"
import { TooltipProvider } from "@/components/ui/tooltip"
import Footer from "@/components/layout/footer"
import "./globals.css"

const outfit = localFont({
  src: "./fonts/outfit-latin.woff2",
  weight: "100 900",
  style: "normal",
  display: "swap",
  variable: "--font-outfit",
  preload: true,
  fallback: ["system-ui", "sans-serif"],
})

const allTopics = getAllTopics()
const topicCounts = getTopicCounts()
const totalTools = getStats().tools
// 0 工具的主题（如「未分类」）不进导航：点进去只会得到空页
const navTopics = allTopics.filter((topic) => (topicCounts[topic.id] ?? 0) > 0)

const jsonLd = {
  "@context": "https://schema.org",
  "@type": "WebSite",
  name: "XiGee",
  alternateName: "XiGee — 精选 AI 工具目录",
  url: getBaseUrl(),
  potentialAction: {
    "@type": "SearchAction",
    target: `${getBaseUrl()}/search?q={search_term_string}`,
    "query-input": "required name=search_term_string",
  },
}

/** JSON-LD 注入前转义 `<`，避免内容中的 </script> 提前闭合脚本标签。 */
const jsonLdString = JSON.stringify(jsonLd).replace(/</g, "\\u003c")

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
}

export const metadata: Metadata = {
  metadataBase: new URL(getBaseUrl()),
  title: { default: "XiGee — 精选 AI 工具目录", template: "%s — XiGee" },
  description: "XiGee 精选值得用的 AI 工具，人工筛选、主题清晰，点击直达官方网站。",
  keywords: ["AI", "AI工具", "人工智能", "AI导航", "AI目录", "AI工具目录", "XiGee"],
  appleWebApp: {
    capable: true,
    title: "XiGee",
    statusBarStyle: "default",
  },
  openGraph: {
    title: "XiGee — 精选 AI 工具目录",
    description: "精选值得用的 AI 工具，每一款都经过人工筛选，点击直达官方网站。",
    siteName: "XiGee",
    locale: "zh_CN",
    type: "website",
  },
}

/**
 * 首帧偏好引导脚本（必须内联在 <head> 且同步执行，早于首次绘制）。
 *
 * 曾经用 next/script beforeInteractive，但它会被塞进 `self.__next_s` 队列、
 * 等 Next 运行时 chunk 加载后才执行 —— 首绘已发生，于是出现「先默认、后跳变」闪烁。
 * 改为 <head> 内联 <script> 后，浏览器解析到即执行，先于 body 解析与首绘。
 *
 * 只做「读偏好 → 写 <html> 属性」，具体渲染交给 CSS（首帧）与 React（hydration 后接管）。
 */
const prefsScript = `(function(){try{
var d=document.documentElement,P=${JSON.stringify(STORAGE_PREFIX)};
var g=function(k){try{return localStorage.getItem(k)}catch(e){return null}};
var t=g("theme")||"system";
var m=window.matchMedia("(prefers-color-scheme:dark)");
var dark=t==="dark"||(t==="system"&&m.matches);
d.classList.toggle("dark",dark);
d.setAttribute("data-theme",t==="light"||t==="dark"||t==="system"?t:"system");
var meta=document.querySelector('meta[name="theme-color"]');
if(meta)meta.setAttribute("content",dark?${JSON.stringify(BRAND_PAGE.dark)}:${JSON.stringify(BRAND_PAGE.light)});
var sb=g(P+":sidebar-collapsed")==="true";
d.setAttribute("data-sidebar",sb?"collapsed":"expanded");
try{var h=JSON.parse(g(P+":history")||"[]");var arr=Array.isArray(h)?h:(h&&Array.isArray(h.items)?h.items:[]);if(arr.length)d.setAttribute("data-history","has")}catch(e){}
var p=new URLSearchParams(location.search);
var view=p.get("view")||g(P+":default-view")||"";
var sort=p.get("sort")||g(P+":default-sort")||"";
var tab=p.get("tab")||g(P+":default-tab")||"";
var pending=(view&&view!=="grid")||(sort&&sort!=="recommended")||(tab&&tab!=="all");
if(pending){
d.setAttribute("data-prefs","pending");
setTimeout(function(){d.removeAttribute("data-prefs")},2000)
}
}catch(e){}})()`

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="zh-CN" className={`${outfit.variable} h-full antialiased`} suppressHydrationWarning>
      <head>
        <meta name="theme-color" content={BRAND_PAGE.light} />
        {/* 必须最先执行：同步内联脚本，早于首绘应用主题 / 侧栏 / 工具偏好的首帧状态 */}
        <script dangerouslySetInnerHTML={{ __html: prefsScript }} />
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLdString }} />
      </head>
      <body className="min-h-full flex flex-col pb-[env(safe-area-inset-bottom)] md:h-[100dvh] md:overflow-hidden">
        <HistoryTracker />
        <PwaRegister />
        <TooltipProvider>
          <a
            href="#main"
            className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[100] focus:rounded-md focus:bg-primary focus:px-4 focus:py-2 focus:text-sm focus:text-primary-foreground"
          >
            跳到主要内容
          </a>
          {/* 首帧偏好由 <head> 内联 prefsScript 在首绘前写入 <html>，此处不再使用 next/script */}
          <Header className="md:hidden" topics={navTopics} topicCounts={topicCounts} totalTools={totalTools} />
          <SubNav className="md:hidden" topics={navTopics} />
          {/* DSH 双表面骨架：左栏灰（sidebar）/ 右区白（main） */}
          <div className="flex flex-1 md:overflow-hidden">
            <Sidebar topics={navTopics} topicCounts={topicCounts} totalTools={totalTools} />
            <div className="flex min-w-0 flex-1 flex-col bg-background md:overflow-hidden">
              <MainHeader className="hidden md:block" topics={allTopics} />
              <div
                id="scroll-container"
                className="flex flex-1 scroll-smooth flex-col scroll-pt-28 md:min-h-0 md:overflow-y-auto"
              >
                <main
                  id="main"
                  tabIndex={-1}
                  className={pageShell("browse", "scroll-mt-16 px-4 py-6 sm:px-6 flex-1 outline-none")}
                >
                  {children}
                </main>
                <Footer />
              </div>
            </div>
          </div>
        </TooltipProvider>
      </body>
    </html>
  )
}
