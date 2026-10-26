import type { NextConfig } from "next"
import bundleAnalyzer from "@next/bundle-analyzer"
import { fileURLToPath } from "node:url"
import { dirname, resolve } from "node:path"

const withBundleAnalyzer = bundleAnalyzer({
  enabled: process.env.ANALYZE === "true",
})

const nextConfig: NextConfig = {
  poweredByHeader: false,
  images: {
    // MVP 阶段无工具图片/logo，统一用首字母或 SVG 图标；引入图片后改回 remotePatterns + 开启优化
    unoptimized: true,
  },
  turbopack: {
    root: resolve(dirname(fileURLToPath(import.meta.url))),
  },
  async headers() {
    const isDev = process.env.NODE_ENV === "development"
    const scriptSrc = isDev ? "'self' 'unsafe-inline' 'unsafe-eval'" : "'self' 'unsafe-inline'"
    const csp = [
      "default-src 'self'",
      "img-src 'self' data: https:",
      "font-src 'self' data:",
      "style-src 'self' 'unsafe-inline'",
      `script-src ${scriptSrc}`,
      "connect-src 'self'",
      "worker-src 'self'",
      "manifest-src 'self'",
      "object-src 'none'",
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "form-action 'self'",
    ].join("; ")

    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
          { key: "Content-Security-Policy", value: csp },
        ],
      },
      // 图标/生成的 PNG 带内容哈希查询串，可安全长缓存；manifest 一年太长，按小时回源。
      {
        source: "/icon/:path*",
        headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }],
      },
      {
        source: "/apple-icon",
        headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }],
      },
      {
        source: "/sw.js",
        headers: [{ key: "Cache-Control", value: "public, max-age=0, must-revalidate" }],
      },
      {
        source: "/manifest.webmanifest",
        headers: [{ key: "Cache-Control", value: "public, max-age=3600, stale-while-revalidate=86400" }],
      },
    ]
  },
}

export default withBundleAnalyzer(nextConfig)
