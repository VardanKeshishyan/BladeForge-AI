import { NextResponse, type NextRequest } from 'next/server'

// Keep old account/setup bookmarks useful in the local app.
export function proxy(request: NextRequest) {
  const path = request.nextUrl.pathname
  const retired: Record<string, string> = {
    '/app': '/app/overview',
    '/app/team': '/app/overview',
    '/app/defect-library': '/app/generate',
    '/app/docs': '/',
    '/onboarding': '/app/generate',
  }
  const destination = path.startsWith('/auth/') ? '/app/generate' : retired[path]
  if (destination) {
    const url = request.nextUrl.clone()
    url.pathname = destination
    url.search = ''
    return NextResponse.redirect(url)
  }
  return NextResponse.next()
}

export const config = { matcher: ['/app/:path*', '/auth/:path*', '/onboarding'] }
