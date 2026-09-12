import Image from 'next/image'
import Link from 'next/link'

import { cn } from '@/lib/utils'

interface BrandButtonProps {
  href?: string
  className?: string
  iconClassName?: string
  textClassName?: string
  label?: string
}

export function BrandButton({
  href = '/',
  className,
  iconClassName,
  textClassName,
  label = 'BladeForge AI home',
}: BrandButtonProps) {
  return (
    <Link
      href={href}
      aria-label={label}
      className={cn(
        'inline-flex min-w-0 items-center gap-2 rounded-md px-2 py-1.5 -ml-2 text-left transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
        className,
      )}
    >
      <Image
        src="/logo_blade.png"
        alt=""
        width={36}
        height={36}
        className={cn('h-9 w-9 flex-shrink-0 object-contain', iconClassName)}
      />
      <span className={cn('text-sm font-semibold truncate', textClassName)}>BladeForge AI</span>
    </Link>
  )
}
