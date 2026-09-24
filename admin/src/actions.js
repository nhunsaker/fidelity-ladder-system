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
    // Say where it actually went. `via: temporal` means the run took it as a signal and moves on
    // its own; the issue path needs the signed webhook round-trip first.
    toast(r.via === 'temporal'
      ? `${text.trim().split('\n')[0]} sent to the run`
      : r.command
        ? `${text.trim().split('\n')[0]} sent — the webhook round-trip applies it`
        : 'Feedback posted to the issue thread')
    onDone?.()
    return true
  } catch (ex) {
    // The harness says WHY, in a sentence written to be read. This branch threw that away and
    // GUESSED — and the guess was wrong for every refusal that was not about those two things.
    // Live proof: an Advance on an expedition whose number collides with a pull request is now
    // refused for exactly that reason, and the operator was still told "no linked issue or no
    // outbound token". The same catch was fixed in Detail; this is the copy the Inbox uses.
    toast(`Refused: ${ex?.message || 'the harness would not accept that'}`)
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
  } catch (ex) {
    toast(`Kill refused: ${ex?.message || 'nothing changed'}`)
    return false
  }
}

/** Pick a stopped run up again from the step that stopped it. Returns true on success.
 *
 *  NOT a signal, and deliberately so: the thing it acts on cannot receive signals, because a
 *  failed workflow is closed and every approve/pick/kill sent to one comes back 409. That is the
 *  hole a stopped run used to fall into — no action on any screen could reach it.
 *
 *  The engine's refusal names which rule it hit (still running · no run · past the ceiling ·
 *  already finished) and it is shown verbatim, because an operator looking at a stuck run needs
 *  to know WHICH of those it is. A generic failure teaches nothing.
 */
export async function retryExpedition(number, who, toast, onDone) {
  if (!who.trim()) { toast('Refused: a retry requires a named actor (fail-closed)'); return false }
  try {
    const r = await api.retry(number, { actor: who.trim() })
    toast(`#${number} picked up again from where it stopped (run ${String(r.run_id).slice(0, 8)})`)
    onDone?.()
    return true
  } catch (ex) {
    toast(`Retry refused: ${ex?.message || 'the harness would not accept that'}`)
    return false
  }
}
