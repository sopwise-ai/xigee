"use client"

import { ChevronDown, type LucideIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuRadioItemIndicator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { cn } from "@/lib/utils"

export interface FilterOption {
  value: string
  label: string
}

interface FilterSelectProps {
  label: string
  icon: LucideIcon
  value: string
  options: FilterOption[]
  onChange: (value: string) => void
  active?: boolean
}

/** 工具条上的紧凑筛选下拉：触发按钮显示当前选中项，菜单单选。 */
export function FilterSelect({ label, icon: Icon, value, options, onChange, active }: FilterSelectProps) {
  const selected = options.find((o) => o.value === value)

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            variant="outline"
            aria-label={label}
            className={cn(
              "gap-1.5 text-xs",
              active
                ? "border-brand/40 bg-brand/10 text-brand hover:border-brand/40 hover:bg-brand/10 hover:text-brand"
                : "text-muted-foreground",
            )}
          />
        }
      >
        <Icon data-icon="inline-start" aria-hidden />
        <span className="whitespace-nowrap">{selected?.label ?? label}</span>
        <ChevronDown data-icon="inline-end" className="opacity-60" aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="max-h-80 min-w-[9rem] overflow-y-auto">
        <DropdownMenuRadioGroup value={value} onValueChange={(next) => onChange(String(next))}>
          {options.map((option) => (
            <DropdownMenuRadioItem key={option.value} value={option.value} className="pr-8 pl-2 text-xs">
              {option.label}
              <DropdownMenuRadioItemIndicator />
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
