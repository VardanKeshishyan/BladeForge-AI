export default function AppLoading() {
  return (
    <div className="flex-1 p-6">
      <div className="h-5 w-40 bg-muted mb-6" />
      <div className="grid grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <div key={index} className="h-24 border border-border bg-muted/30" />
        ))}
      </div>
    </div>
  )
}

