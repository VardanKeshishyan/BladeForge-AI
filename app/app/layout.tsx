import { AppSidebar } from '@/components/app/sidebar'

export const dynamic = 'force-dynamic'

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-dvh overflow-hidden bg-background">
      <AppSidebar />
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">{children}</div>
    </div>
  )
}
