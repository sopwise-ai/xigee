import type { Metadata } from "next"
import Link from "next/link"
import { CloudOff } from "lucide-react"
import { PageStatus } from "@/components/system/page-status"
import { Button } from "@/components/ui/button"

export const metadata: Metadata = {
  title: "离线",
  robots: { index: false },
}

export default function OfflinePage() {
  return (
    <PageStatus
      code="OFFLINE"
      media={<CloudOff className="size-6" />}
      title="当前处于离线状态"
      description="已缓存的页面和本地历史仍可查看；联网后刷新即可继续探索新工具。"
      actions={<Button render={<Link href="/" />}>返回首页</Button>}
    />
  )
}
