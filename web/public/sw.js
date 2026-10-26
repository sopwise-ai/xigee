/* XiGee service worker：离线壳 + 已访问页面 + 索引缓存。
 *
 * 不 precache 全站：Next 的 hash chunk 太多，手写清单会随构建漂移；
 * 首次访问后用 runtime cache 渐进填充，离线时至少能打开壳、历史页与看过的页面。
 * 更新策略：新 SW 安装后等待，下一次导航由浏览器接管；不做 skipWaiting 以免混用新旧 chunk。
 */
const VERSION = "xigee-v2"
const SHELL_CACHE = `${VERSION}-shell`
const PAGES_CACHE = `${VERSION}-pages`
const ASSET_CACHE = `${VERSION}-assets`
const DATA_CACHE = `${VERSION}-data`
const SHELL = ["/", "/search", "/history", "/offline", "/manifest.webmanifest"]

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL))
      .catch(() => undefined),
  )
})

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => !key.startsWith(VERSION)).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  )
})

async function trimCache(name, maxEntries) {
  const cache = await caches.open(name)
  const keys = await cache.keys()
  for (let i = 0; i < keys.length - maxEntries; i++) await cache.delete(keys[i])
}

async function cachePage(request, response) {
  const cache = await caches.open(PAGES_CACHE)
  await cache.put(request, response)
  await trimCache(PAGES_CACHE, 30)
}

async function networkFirstPage(request) {
  try {
    const response = await fetch(request)
    if (response.ok) await cachePage(request, response.clone())
    return response
  } catch {
    const url = new URL(request.url)
    const routeFallback = url.pathname.startsWith("/search") ? await caches.match("/search") : undefined
    const cached =
      (await caches.match(request)) || routeFallback || (await caches.match("/")) || (await caches.match("/offline"))
    return (
      cached ||
      new Response("离线且没有缓存页面", { status: 503, headers: { "Content-Type": "text/plain; charset=utf-8" } })
    )
  }
}

async function cacheFirstAsset(request) {
  const cached = await caches.match(request)
  if (cached) return cached
  const response = await fetch(request)
  if (response.ok) {
    const cache = await caches.open(ASSET_CACHE)
    await cache.put(request, response.clone())
  }
  return response
}

async function staleWhileRevalidateIndex(request) {
  const cache = await caches.open(DATA_CACHE)
  const cached = await cache.match(request)
  const network = fetch(request)
    .then((response) => {
      if (response.ok) cache.put(request, response.clone())
      return response
    })
    .catch(() => undefined)
  return cached || network
}

self.addEventListener("fetch", (event) => {
  const request = event.request
  if (request.method !== "GET") return
  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return

  if (request.mode === "navigate") {
    event.respondWith(networkFirstPage(request))
    return
  }

  if (url.pathname.startsWith("/_next/static/") || /\.(?:css|js|woff2?|png|svg|ico)$/.test(url.pathname)) {
    event.respondWith(cacheFirstAsset(request))
    return
  }

  if (url.pathname === "/api/index") {
    event.respondWith(staleWhileRevalidateIndex(request))
  }
})
