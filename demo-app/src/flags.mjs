// Feature-flag resolution for Acme. Pure, dependency-free (node:test can exercise it).
import flags from '../flags.json' with { type: 'json' }

export function isEnabled(name, env) {
  const f = flags[name]
  return !!(f && f[env] === true)
}
