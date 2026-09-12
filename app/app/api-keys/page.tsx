import { serverApiRequest } from '@/lib/api/server'
import { ApiKeysClient } from './api-keys-client'

export default async function ApiKeysPage() {
  const result = await serverApiRequest<{ items: Parameters<typeof ApiKeysClient>[0]['initialKeys'] }>(
    '/v1/api-keys',
  )
  return <ApiKeysClient initialKeys={result.items} />
}
