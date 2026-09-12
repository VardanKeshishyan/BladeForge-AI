'use client'

import { useState } from 'react'
import { Key, Plus, X } from 'lucide-react'
import { AppTopBar } from '@/components/app/topbar'
import { apiRequest } from '@/lib/api/client'

type SafeApiKey = {
  id: string
  name: string
  key_prefix: string
  status: 'active' | 'revoked'
  expires_at: string | null
  last_used_at: string | null
  revoked_at: string | null
  created_at: string
}

export function ApiKeysClient({ initialKeys }: { initialKeys: SafeApiKey[] }) {
  const [keys, setKeys] = useState(initialKeys)
  const [name, setName] = useState('')
  const [creating, setCreating] = useState(false)
  const [newKey, setNewKey] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function createKey(event: React.FormEvent) {
    event.preventDefault()
    if (creating) return
    setCreating(true)
    setError(null)
    try {
      const created = await apiRequest<SafeApiKey & { key: string }>('/v1/api-keys', {
        method: 'POST',
        body: JSON.stringify({ name, expires_at: null }),
      })
      setKeys((current) => [{ ...created, key: undefined } as SafeApiKey, ...current])
      setNewKey(created.key)
      setName('')
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Key creation failed.')
    } finally {
      setCreating(false)
    }
  }

  async function revoke(keyId: string) {
    try {
      const revoked = await apiRequest<SafeApiKey>(`/v1/api-keys/${keyId}/revoke`, {
        method: 'POST',
      })
      setKeys((current) => current.map((key) => key.id === keyId ? revoked : key))
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Key revocation failed.')
    }
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <AppTopBar breadcrumbs={[{ label: 'API Keys' }]} />
      <main className="flex-1 overflow-y-auto p-6">
        <div className="max-w-3xl">
          <div className="flex items-start justify-between mb-6">
            <div>
              <h1 className="text-xl font-bold">API keys</h1>
              <p className="text-sm text-muted-foreground mt-0.5">
                Keys are shown in full once. BladeForge stores only a keyed hash.
              </p>
            </div>
          </div>

          <form onSubmit={createKey} className="flex gap-2 mb-6">
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              minLength={2}
              maxLength={100}
              required
              placeholder="Key name"
              className="h-8 flex-1 px-3 text-xs border border-input bg-background"
            />
            <button
              disabled={creating}
              className="inline-flex items-center gap-1.5 h-8 bg-primary text-primary-foreground px-3 text-xs disabled:opacity-50"
            >
              <Plus className="w-3.5 h-3.5" />
              {creating ? 'Creating…' : 'Create key'}
            </button>
          </form>

          {newKey && (
            <div className="border border-primary/30 bg-accent p-4 mb-6">
              <div className="flex items-center justify-between mb-2">
                <strong className="text-xs">Copy this key now. It will not be shown again.</strong>
                <button onClick={() => setNewKey(null)} aria-label="Dismiss"><X className="w-4 h-4" /></button>
              </div>
              <code className="text-xs font-mono break-all select-all">{newKey}</code>
            </div>
          )}
          {error && <div className="text-xs text-destructive mb-4">{error}</div>}

          {keys.length === 0 ? (
            <div className="border border-dashed border-border bg-muted/30 p-12 text-center">
              <Key className="w-8 h-8 text-border mx-auto mb-4" />
              <h2 className="text-sm font-semibold mb-1">No API keys yet</h2>
              <p className="text-sm text-muted-foreground">Create a key for server-side API access.</p>
            </div>
          ) : (
            <div className="border border-border bg-card">
              <div className="grid grid-cols-[1fr_180px_90px_80px] gap-4 px-5 py-2 text-[10px] uppercase text-muted-foreground border-b border-border">
                <span>Name</span><span>Key</span><span>Status</span><span>Action</span>
              </div>
              <div className="divide-y divide-border">
                {keys.map((key) => (
                  <div key={key.id} className="grid grid-cols-[1fr_180px_90px_80px] gap-4 px-5 py-3 items-center">
                    <span className="text-sm font-medium">{key.name}</span>
                    <span className="text-xs font-mono text-muted-foreground">{key.key_prefix}••••••••</span>
                    <span className={key.status === 'active' ? 'text-xs text-emerald-600' : 'text-xs text-muted-foreground'}>{key.status}</span>
                    {key.status === 'active' ? (
                      <button onClick={() => revoke(key.id)} className="text-xs text-destructive text-left">Revoke</button>
                    ) : <span className="text-xs text-muted-foreground">—</span>}
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="mt-8 border border-border bg-card p-5">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">Authentication</h2>
            <pre className="bg-[#0e1117] text-green-400 text-xs font-mono p-4 overflow-x-auto">
{`curl "$BLADEFORGE_API_URL/v1/external/jobs" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "Idempotency-Key: YOUR_UNIQUE_REQUEST_ID"`}
            </pre>
          </div>
        </div>
      </main>
    </div>
  )
}

