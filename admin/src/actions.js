// Shared human-in-the-loop wiring — the named-actor feedback/kill posts used by both the
// Workbench Inbox (inline actions) and Detail. ONE protocol: feedback becomes an issue comment;
// commands (/advance · /pick N · /approve) only take effect when the signed webhook echoes them
// back. Fail-closed: every action requires a named actor, or it refuses with a toast.
import { api } from './api.js'

/** Post feedback (or a command) to an expedition's issue thread. Returns true on success. */
export async function postFeedback(number, text, who, toast, onDone) {
  if (!who.trim()) { toast('Refused: this action requires a named actor (fail-closed)'); return false }
  if (!text.trim()) { toast('Nothing to send'); return false }
  try {
    const r = await api.feedback(number, { body: text.trim(), actor: who.trim() })
    toast(r.command
      ? `${text.trim().split('\n')[0]} sent — the webhook round-trip applies it`
      : 'Feedback posted to the issue thread')
    onDone?.()
    return true
  } catch {
    toast('Feedback refused by the harness (no linked issue or no outbound token)')
    return false
  }
}

/** Park (kill) an expedition. Returns true on success. */
export async function killExpedition(number, who, toast, onDone) {
  if (!who.trim()) { toast('Refused: the kill switch requires a named actor (fail-closed)'); return false }
  try {
    await api.kill(number, { actor: who.trim(), reason: 'killed from admin inbox' })
    toast(`#${number} parked by ${who.trim()} — recorded in the ledger`)
    onDone?.()
    return true
  } catch {
    toast('Kill request failed against the live harness — nothing changed')
    return false
  }
}
