import type { MetadataRoute } from "next"
import { BRAND_PAGE } from "@/lib/brand"

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "XiGee — 精选 AI 工具目录",
    short_name: "XiGee",
    description: "精选值得用的 AI 工具，每一款都经过人工筛选，点击直达官方网站。",
    lang: "zh-CN",
    id: "/",
    start_url: "/",
    scope: "/",
    display: "standalone",
    display_override: ["standalone", "minimal-ui"],
    launch_handler: { client_mode: "navigate-existing" },
    categories: ["productivity", "utilities"],
    background_color: BRAND_PAGE.light,
    theme_color: BRAND_PAGE.light,
    shortcuts: [
      {
        name: "探索精选",
        short_name: "精选",
        description: "直接打开人工精选的 AI 工具",
        url: "/?tab=featured",
        icons: [{ src: "/icon/96", sizes: "96x96", type: "image/png" }],
      },
      {
        name: "历史记录",
        short_name: "历史",
        description: "回到最近看过的工具",
        url: "/history",
        icons: [{ src: "/icon/96", sizes: "96x96", type: "image/png" }],
      },
      {
        name: "设置",
        short_name: "设置",
        description: "外观与浏览偏好",
        url: "/settings",
        icons: [{ src: "/icon/96", sizes: "96x96", type: "image/png" }],
      },
    ],
    icons: [
      {
        src: "/icon/32",
        sizes: "32x32",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icon/96",
        sizes: "96x96",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icon/192",
        sizes: "192x192",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icon/192",
        sizes: "192x192",
        type: "image/png",
        purpose: "maskable",
      },
      {
        src: "/icon/512",
        sizes: "512x512",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icon/512",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
      {
        src: "/apple-icon",
        sizes: "180x180",
        type: "image/png",
        purpose: "any",
      },
    ],
  }
}
