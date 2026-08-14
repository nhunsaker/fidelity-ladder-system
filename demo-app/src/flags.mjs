// Feature-flag resolution for Acme. Pure, dependency-free (node:test can exercise it).
import flags from '../flags.json' with { type: 'json' }

/** Pure check against any flags object (the app fetches /flags.json at runtime). */
export function flagEnabled(flagsObj, name, env) {
  const f = flagsObj?.[name]
  return !!(f && f[env] === true)
}

/** Static check against the committed flags.json (node tests + rung-4 targets). */
export function isEnabled(name, env) {
  return flagEnabled(flags, name, env)
}
