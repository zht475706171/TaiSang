export async function apiGet<T>(url: string): Promise<T> {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`GET ${url} failed: ${r.status}`)
  return (await r.json()) as T
}

export async function apiPost<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`POST ${url} failed: ${r.status}`)
  return (await r.json()) as T
}

export async function apiDelete<T>(url: string): Promise<T> {
  const r = await fetch(url, { method: 'DELETE' })
  if (!r.ok) throw new Error(`DELETE ${url} failed: ${r.status}`)
  return (await r.json()) as T
}