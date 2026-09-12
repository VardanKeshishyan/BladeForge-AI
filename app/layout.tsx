import type { Metadata, Viewport } from 'next'
import { Inter, JetBrains_Mono } from 'next/font/google'
import './globals.css'

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
})

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-jetbrains-mono',
})

export const metadata: Metadata = {
  title: 'BladeForge AI — Synthetic Wind-Turbine Blade Defect Data',
  description:
    'A local workspace for wind-turbine inspection images, painted defect regions, Blender rendering, and dataset exports.',
  keywords: [
    'wind turbine',
    'blade inspection',
    'synthetic data',
    'defect detection',
    'computer vision',
    'machine learning',
  ],
  icons: {
    icon: '/logo_blade.png',
    shortcut: '/logo_blade.png',
    apple: '/logo_blade.png',
  },
}

export const viewport: Viewport = {
  colorScheme: 'light',
  themeColor: '#fafafa',
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" className="bg-background">
      <body className={`${inter.variable} ${jetbrainsMono.variable} antialiased font-sans`}>
        {children}
      </body>
    </html>
  )
}
