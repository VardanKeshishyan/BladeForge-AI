export { ApiError, localApiRequest as apiRequest } from './http'

export function createIdempotencyKey(scope: string) {
  return `${scope}-${crypto.randomUUID()}`
}
