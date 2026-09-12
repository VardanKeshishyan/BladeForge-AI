export const API_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly code: string,
    public readonly status: number,
    public readonly requestId?: string,
  ) {
    super(message)
  }
}

export async function localApiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (!(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  let response: Response
  try {
    response = await fetch(`${API_URL}${path}`, { ...options, headers })
  } catch {
    throw new ApiError('Cannot reach the local backend. Start it and try again.', 'backend_unavailable', 0)
  }
  if (response.status === 204) return undefined as T
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    throw new ApiError(
      response.status === 401
        ? 'The backend requires authentication. Enable its existing local-access setting for this local app.'
        : payload?.error?.message ?? 'The request could not be completed.',
      payload?.error?.code ?? 'request_failed', response.status, payload?.error?.request_id,
    )
  }
  if (payload === null) throw new ApiError('The backend returned an unreadable response.', 'invalid_response', response.status)
  return payload as T
}
