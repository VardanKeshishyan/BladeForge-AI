'use client'

export default function GlobalError({
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-6">
      <div className="max-w-sm text-center">
        <h1 className="text-xl font-bold mb-2">Something went wrong</h1>
        <p className="text-sm text-muted-foreground mb-5">
          The request could not be completed. No sensitive error details were exposed.
        </p>
        <button onClick={reset} className="h-9 px-4 bg-primary text-primary-foreground text-sm">
          Try again
        </button>
      </div>
    </div>
  )
}

