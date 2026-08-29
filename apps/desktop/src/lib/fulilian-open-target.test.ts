import { describe, expect, it } from 'vitest'

import {
  normalizeFulilianOpenString,
  pathFromFulilianDeepLink,
  pathFromOpenDeepLink,
  resolveFulilianOpenPath
} from './fulilian-open-target'

describe('normalizeFulilianOpenString', () => {
  it('accepts hash-router paths and strips a leading hash', () => {
    expect(normalizeFulilianOpenString('/index-network/intent/1')).toBe('/index-network/intent/1')
    expect(normalizeFulilianOpenString('#/index-network/intent/1')).toBe('/index-network/intent/1')
  })

  it('maps plugin-scoped fulilian:// deep links to the same path', () => {
    expect(normalizeFulilianOpenString('fulilian://index-network/intent/1')).toBe('/index-network/intent/1')
    expect(normalizeFulilianOpenString('fulilian://index-network/intent/1?focus=true')).toBe(
      '/index-network/intent/1?focus=true'
    )
  })

  it('maps fulilian://open/… deep links by stripping the open host', () => {
    expect(normalizeFulilianOpenString('fulilian://open/index-network/intent/1')).toBe('/index-network/intent/1')
    expect(normalizeFulilianOpenString('fulilian://open/settings/plugins')).toBe('/settings/plugins')
  })

  it('rejects reserved fulilian kinds and unsafe paths', () => {
    expect(normalizeFulilianOpenString('fulilian://blueprint/morning-brief')).toBeNull()
    expect(normalizeFulilianOpenString('fulilian://plugin/install')).toBeNull()
    expect(normalizeFulilianOpenString('https://example.com/x')).toBeNull()
    expect(normalizeFulilianOpenString('/../etc/passwd')).toBeNull()
    expect(normalizeFulilianOpenString('index-network')).toBeNull()
  })
})

describe('resolveFulilianOpenPath', () => {
  it('merges structured path + params', () => {
    expect(resolveFulilianOpenPath({ path: '/index-network/intent/1', params: { focus: 'true' } })).toBe(
      '/index-network/intent/1?focus=true'
    )
  })

  it('resolves href the same as a bare string', () => {
    expect(resolveFulilianOpenPath({ href: 'fulilian://index-network/intent/1' })).toBe('/index-network/intent/1')
  })
})

describe('pathFromFulilianDeepLink', () => {
  it('builds the navigate path from a plugin-scoped deep-link payload', () => {
    expect(pathFromFulilianDeepLink('index-network', 'intent/1')).toBe('/index-network/intent/1')
  })

  it('builds the navigate path from fulilian://open/… payloads', () => {
    expect(pathFromOpenDeepLink('index-network/intent/1')).toBe('/index-network/intent/1')
    expect(pathFromFulilianDeepLink('open', 'agent/42')).toBe('/agent/42')
  })

  it('ignores reserved kinds', () => {
    expect(pathFromFulilianDeepLink('blueprint', 'morning-brief')).toBeNull()
    expect(pathFromFulilianDeepLink('plugin', 'install')).toBeNull()
  })
})
