import 'server-only'
import { localApiRequest } from './http'

export function serverApiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  return localApiRequest<T>(path, { ...options, cache: 'no-store' })
}
