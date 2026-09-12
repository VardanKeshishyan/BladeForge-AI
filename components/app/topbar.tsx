import Link from 'next/link'
import { Zap } from 'lucide-react'

interface TopBarProps {
  breadcrumbs?: { label: string; href?: string }[]
}

export function AppTopBar({ breadcrumbs = [] }: TopBarProps) {
  return (
    <header className="h-14 border-b border-border bg-card flex items-center justify-between gap-3 px-4 md:px-6 shrink-0">
      <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground overflow-hidden">
        {breadcrumbs.map((crumb, index) => (
          <span key={`${crumb.label}-${index}`} className="flex min-w-0 items-center gap-1.5">
            {index > 0 && <span aria-hidden="true" className="text-border">/</span>}
            {crumb.href ? <Link href={crumb.href} className="truncate hover:text-foreground">{crumb.label}</Link>
              : <span aria-current="page" className="truncate text-foreground font-medium">{crumb.label}</span>}
          </span>
        ))}
      </nav>
      <Link href="/app/generate" className="shrink-0 inline-flex items-center gap-1.5 rounded-md bg-primary text-primary-foreground px-3 py-2 text-xs font-medium hover:opacity-90 transition-opacity">
        <Zap className="size-3.5" aria-hidden="true" /><span className="hidden sm:inline">New generation</span><span className="sm:hidden">New</span>
      </Link>
    </header>
  )
}
