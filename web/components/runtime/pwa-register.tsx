"use client"

import { useEffect } from "react"

/**
 * 仅生产环境注册 Service Worker：
 * dev 的 HMR / 动态 chunk 不适合被 SW 缓存，容易造成“改了不生效”的假象。
 */
export function PwaRegister() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") return
    if (!("serviceWorker" in navigator)) return

    const register = () => {
      navigator.serviceWorker.register("/sw.js").catch((error: unknown) => {
        console.error("[pwa] Service Worker 注册失败", error)
      })
    }

    if (document.readyState === "complete") register()
    else window.addEventListener("load", register, { once: true })
    return () => window.removeEventListener("load", register)
  }, [])

  return null
}
