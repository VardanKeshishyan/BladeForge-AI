'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { LayoutDashboard, Zap, Database, BarChart2, Settings, Monitor, ListOrdered, ArrowLeft } from 'lucide-react'
import { BrandButton } from '@/components/app/brand-button'

const MAIN_ITEMS = [
  { href: '/app/overview', icon: LayoutDashboard, label: 'Overview' },
  { href: '/app/generate', icon: Zap, label: 'New Generation' },
  { href: '/app/jobs', icon: ListOrdered, label: 'Jobs' },
  { href: '/app/datasets', icon: Database, label: 'Datasets' },
]
const WORKSPACE_ITEMS = [
  { href: '/app/usage', icon: BarChart2, label: 'Usage' },
  { href: '/app/settings', icon: Settings, label: 'Settings' },
]

export function AppSidebar() {
  const pathname = usePathname()
  return (
    <aside className="w-16 md:w-[220px] shrink-0 bg-sidebar border-r border-sidebar-border flex flex-col h-dvh">
      <div className="h-14 border-b border-sidebar-border flex items-center px-3 md:px-4 shrink-0">
        <BrandButton href="/app/overview" label="BladeForge AI overview" className="max-w-full hover:bg-sidebar-accent" iconClassName="h-9 w-9" textClassName="hidden md:block text-sidebar-foreground" />
      </div>
      <div className="hidden md:flex items-center gap-2.5 px-5 py-5 text-sidebar-foreground/70">
        <Monitor className="size-4 text-sidebar-primary" aria-hidden="true" />
        <div><p className="text-xs font-medium text-sidebar-foreground">Local workspace</p><p className="text-[10px] mt-0.5">Your turbine inspection toolkit</p></div>
      </div>
      <nav aria-label="Workspace navigation" className="flex-1 overflow-y-auto px-2 py-3 md:pt-0">
        {[MAIN_ITEMS, WORKSPACE_ITEMS].map((items, group) => (
          <div key={group} className={group ? 'mt-6 pt-4 border-t border-sidebar-border space-y-1' : 'space-y-1'}>
            {items.map(({ href, icon: Icon, label }) => {
              const active = pathname === href || pathname.startsWith(href + '/')
              return (
                <Link key={href} href={href} title={label} aria-label={label} aria-current={active ? 'page' : undefined}
                  className={`flex items-center justify-center md:justify-start gap-3 rounded-md px-3 py-2.5 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring ${active ? 'bg-sidebar-accent text-sidebar-accent-foreground' : 'text-sidebar-foreground/65 hover:bg-sidebar-accent hover:text-sidebar-foreground'}`}>
                  <Icon className={`size-4 shrink-0 ${active ? 'text-sidebar-primary' : ''}`} strokeWidth={1.6} aria-hidden="true" />
                  <span className="hidden md:inline">{label}</span>
                </Link>
              )
            })}
          </div>
        ))}
      </nav>
      <div className="border-t border-sidebar-border p-3 shrink-0">
        <Link href="/" aria-label="Back to home" className="flex items-center justify-center md:justify-start gap-2 rounded-md px-2 py-2 text-xs text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent">
          <ArrowLeft className="size-3.5" aria-hidden="true" /><span className="hidden md:inline">Back to home</span>
        </Link>
      </div>
    </aside>
  )
}
