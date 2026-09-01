/**
 * Shared resolver for in-app navigation targets that must stay compatible with
 * `fulilian://` deep links and `host.navigate('/path?…')`.
 *
 * Notification activation, deep-link delivery, and plugin `activate` payloads
 * all funnel through here so a toast click and an OS deep link land on the
 * same hash-router path.
 *
 * Supported deep-link shapes:
 *  - `fulilian://index-network/intent/1` → `/index-network/intent/1` (plugin-scoped)
 *  - `fulilian://open/my-page?item=x` → `/my-page?item=x` (generic open)
 *  - `/my-page?item=x` / `#/my-page?item=x` (hash-router paths)
 */

export type FulilianOpenTarget = string | { href: string } | { path: string; params?: Record<string, string> }

const FULILIAN_PROTOCOL = 'fulilian:'

/** Hostnames owned by core deep-link handlers — never treated as plugin routes. */
const RESERVED_DEEP_LINK_KINDS = new Set([
  'blueprint',
  'chat',
  'install',
  'mcp',
  'open',
  'plugin',
  'plugin-agent',
  'plugin-desktop',
  'settings'
])

function appendSearch(path: string, params: URLSearchParams | Record<string, string> | undefined): string {
  if (!params) {
    return path
  }

  const search =
    params instanceof URLSearchParams
      ? params
      : new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== ''))

  const qs = search.toString()

  if (!qs) {
    return path
  }

  return path.includes('?') ? `${path}&${qs}` : `${path}?${qs}`
}

function isSafeAppPath(path: string): boolean {
  if (!path.startsWith('/') || path.startsWith('//')) {
    return false
  }

  // Block traversal and scheme smuggling in the path segment.
  if (path.includes('..') || path.includes('\\') || path.includes(':')) {
    return false
  }

  return true
}

function isPluginDeepLinkHost(host: string): boolean {
  return /^[a-z0-9][a-z0-9-]*$/.test(host) && !RESERVED_DEEP_LINK_KINDS.has(host)
}

/** Normalize a string target to a hash-router path, or null. */
export function normalizeFulilianOpenString(raw: string): string | null {
  const trimmed = raw.trim()

  if (!trimmed) {
    return null
  }

  if (trimmed.startsWith('fulilian://') || trimmed.startsWith(`${FULILIAN_PROTOCOL}//`)) {
    try {
      const url = new URL(trimmed)
      const host = url.hostname || ''
      const rest = decodeURIComponent((url.pathname || '').replace(/^\//, ''))

      // fulilian://open/<path>?… → /<path>?…
      if (host === 'open') {
        if (!rest) {
          return null
        }

        const path = `/${rest}`

        if (!isSafeAppPath(path.split('?')[0] ?? path)) {
          return null
        }

        return appendSearch(path, url.searchParams)
      }

      // fulilian://index-network/intent/1 → /index-network/intent/1
      if (!isPluginDeepLinkHost(host) || !rest) {
        return null
      }

      const path = `/${host}/${rest}`

      if (!isSafeAppPath(path.split('?')[0] ?? path)) {
        return null
      }

      return appendSearch(path, url.searchParams)
    } catch {
      return null
    }
  }

  const path = trimmed.startsWith('#') ? trimmed.slice(1) : trimmed

  if (!isSafeAppPath(path.split('?')[0] ?? path)) {
    return null
  }

  return path
}

/** Resolve any supported activate/open target to a hash-router path, or null. */
export function resolveFulilianOpenPath(target: FulilianOpenTarget | null | undefined): string | null {
  if (target == null) {
    return null
  }

  if (typeof target === 'string') {
    return normalizeFulilianOpenString(target)
  }

  if (typeof target !== 'object') {
    return null
  }

  if ('href' in target && typeof target.href === 'string') {
    return normalizeFulilianOpenString(target.href)
  }

  if ('path' in target && typeof target.path === 'string') {
    const base = normalizeFulilianOpenString(target.path)

    if (!base) {
      return null
    }

    return appendSearch(base, target.params)
  }

  return null
}

/**
 * Build a navigate path from a parsed deep-link payload
 * (`fulilian://<kind>/<name>?…` → kind/name/params).
 */
export function pathFromFulilianDeepLink(
  kind: string,
  name: string,
  params: Record<string, string> = {}
): string | null {
  if (!kind || !name) {
    return null
  }

  if (kind === 'open') {
    return resolveFulilianOpenPath({ path: `/${name.replace(/^\//, '')}`, params })
  }

  if (!isPluginDeepLinkHost(kind)) {
    return null
  }

  return resolveFulilianOpenPath({ path: `/${kind}/${name.replace(/^\//, '')}`, params })
}

/** Convenience for `fulilian://open/<name>?…` payloads. */
export function pathFromOpenDeepLink(name: string, params: Record<string, string> = {}): string | null {
  return pathFromFulilianDeepLink('open', name, params)
}
