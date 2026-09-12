import Link from 'next/link'
import { ArrowRight, Box, Paintbrush, Download, Monitor, SlidersHorizontal, Sparkles } from 'lucide-react'
import { BrandButton } from '@/components/app/brand-button'

const features = [
  { icon: Box, title: 'Bring your turbine', description: 'Use the included model or import an OBJ or FBX. Choose the blades, tower, or another part to inspect.' },
  { icon: Paintbrush, title: 'Define the damage', description: 'Paint specific regions, assign defect types, and adjust severity. Control the camera, environment, and lighting.' },
  { icon: Download, title: 'Review and export', description: 'Follow your jobs and download images, masks, scene metadata, and COCO JSON or YOLO v8 annotations.' },
]

export default function LandingPage() {
  return (
    <div className="min-h-dvh bg-background text-foreground">
      <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur-sm">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-5 sm:px-8">
          <BrandButton textClassName="tracking-tight" />
          <nav aria-label="Main navigation" className="hidden sm:flex items-center gap-6 text-sm text-muted-foreground">
            <a href="#features" className="hover:text-foreground transition-colors">Features</a>
            <a href="#workflow" className="hover:text-foreground transition-colors">How it works</a>
          </nav>
          <Link href="/app/generate" className="rounded-md bg-primary px-4 py-2 text-xs sm:text-sm font-medium text-primary-foreground hover:opacity-90 transition-opacity">
            Let&apos;s get started
          </Link>
        </div>
      </header>

      <main>
        <section className="mx-auto max-w-6xl px-5 sm:px-8 pt-16 sm:pt-24 pb-16 sm:pb-20">
          <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/5 px-3 py-1.5 text-xs font-medium text-primary">
            <Monitor className="size-3.5" aria-hidden="true" /> Built for your local workspace
          </div>
          <h1 className="max-w-4xl text-4xl sm:text-5xl lg:text-6xl font-semibold tracking-tight leading-[1.12] text-balance">
            Turbine inspection data.<br /><span className="text-primary">Under your control.</span>
          </h1>
          <p className="mt-6 max-w-2xl text-base sm:text-lg leading-relaxed text-muted-foreground text-pretty">
            Set up your turbine, paint defect regions, and generate inspection images.
            A focused workspace for experimenting with synthetic data, running on your computer.
          </p>
          <Link href="/app/generate" className="mt-8 inline-flex items-center gap-3 rounded-md bg-primary px-6 py-3 text-sm font-medium text-primary-foreground hover:opacity-90 transition-opacity">
            Let&apos;s get started <ArrowRight className="size-4" aria-hidden="true" />
          </Link>
          <p className="mt-4 text-xs text-muted-foreground">No account or signup. Open the workspace and start creating.</p>
        </section>

        <section id="features" className="scroll-mt-20 border-y border-border bg-muted/25">
          <div className="mx-auto max-w-6xl px-5 sm:px-8 py-14 sm:py-16">
            <p className="text-xs font-mono tracking-wider text-primary">YOUR WORKSPACE</p>
            <h2 className="mt-3 text-2xl sm:text-3xl font-semibold tracking-tight">From model to dataset, in one place.</h2>
            <div className="mt-8 grid gap-4 md:grid-cols-3">
              {features.map(({ icon: Icon, title, description }) => (
                <article key={title} className="rounded-xl border border-border bg-card p-6">
                  <div className="mb-5 flex size-10 items-center justify-center rounded-lg bg-primary/8 text-primary"><Icon className="size-5" strokeWidth={1.6} aria-hidden="true" /></div>
                  <h3 className="text-base font-semibold">{title}</h3>
                  <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{description}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="workflow" className="scroll-mt-20 mx-auto max-w-6xl px-5 sm:px-8 py-14 sm:py-20">
          <p className="text-xs font-mono tracking-wider text-primary">HOW IT WORKS</p>
          <h2 className="mt-3 text-2xl sm:text-3xl font-semibold tracking-tight">Set up. Generate. Inspect.</h2>
          <div className="mt-10 grid gap-8 md:grid-cols-3">
            {[
              { step: '01', title: 'Configure your scene', text: 'Choose a model and view. Paint the regions you want to change and set their defect types.' },
              { step: '02', title: 'Run a generation', text: 'Submit a job to your local Blender worker. Optional Gemini editing adds surface detail using your image and region masks.' },
              { step: '03', title: 'Check the result', text: 'Review the generated images and annotations before using them. Download your dataset when you are ready.' },
            ].map(({ step, title, text }) => (
              <div key={step}>
                <span className="font-mono text-sm text-primary">{step}</span>
                <h3 className="mt-3 text-base font-semibold">{title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{text}</p>
              </div>
            ))}
          </div>
          <div className="mt-12 rounded-xl border border-border bg-muted/30 p-5 sm:p-6 flex gap-4 items-start">
            <Sparkles className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden="true" />
            <div>
              <h3 className="text-sm font-semibold">Gemini editing is optional</h3>
              <p className="mt-1.5 max-w-3xl text-sm leading-relaxed text-muted-foreground">
                Bring your own Gemini API key to enable image editing. Edited images and masks are sent to Google, and API usage may incur charges.
                Exported editing-region masks need review before use as training labels.
              </p>
            </div>
          </div>
        </section>

        <section className="border-t border-border bg-muted/25">
          <div className="mx-auto flex max-w-6xl flex-col sm:flex-row gap-6 items-start sm:items-center justify-between px-5 sm:px-8 py-10">
            <div className="flex items-center gap-3">
              <SlidersHorizontal className="size-5 text-primary" aria-hidden="true" />
              <div><h2 className="text-lg font-semibold">Make your first scene.</h2><p className="mt-1 text-sm text-muted-foreground">Your model, your camera, your defect regions.</p></div>
            </div>
            <Link href="/app/generate" className="inline-flex shrink-0 items-center gap-2 rounded-md border border-primary px-5 py-2.5 text-sm font-medium text-primary hover:bg-primary/5 transition-colors">
              Open workspace <ArrowRight className="size-4" aria-hidden="true" />
            </Link>
          </div>
        </section>
      </main>

      <footer className="border-t border-border">
        <div className="mx-auto max-w-6xl px-5 sm:px-8 py-6 flex flex-wrap items-center justify-between gap-4">
          <BrandButton textClassName="text-xs" />
          <span className="text-xs text-muted-foreground">BladeForge AI · Local edition</span>
        </div>
      </footer>
    </div>
  )
}
