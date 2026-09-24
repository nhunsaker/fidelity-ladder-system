// Who is acting — from the verified session when this instance has one, typed when it does not.
//
// The typed name never had any weight: the harness only checked that the string was non-empty,
// so "Acting as" was a label, not a credential. With identity configured the server now IGNORES
// the typed value entirely, so leaving the box editable would be a lie — it would look like it
// was being used. Read-only, showing the signed-in name, is the honest rendering.
import { useEffect, useState } from 'react'
import { api } from './api.js'

/** @returns {{who: string, setWho: (v: string) => void, verified: boolean}} */
export function useWhoami() {
  const [typed, setTyped] = useState('')
  const [principal, setPrincipal] = useState(null)
  useEffect(() => {
    api.me()
      .then((m) => setPrincipal(m && m.authenticated ? m.principal : null))
      // Swallow everything: throwing inside a .catch only produces an unhandled rejection,
      // and this hook's job is to name the actor, not to decide what a failed /auth/me means.
      // App.jsx owns that decision and has already made it by the time this renders.
      .catch(() => setPrincipal(null))
  }, [])
  if (principal) {
    const name = principal.name || principal.login || principal.subject
    return { who: name, setWho: () => {}, verified: true }
  }
  return { who: typed, setWho: setTyped, verified: false }
}
