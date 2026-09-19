import { useState, type FormEvent } from 'react'

type Attempt = { status: 'ready' } | { status: 'submitting' } | { status: 'refused'; reason: string }

type Props = {
  onSignedIn: () => void
}

/**
 * The PIN screen. Shown only when the cookie is absent, which on a phone means once
 * a year (ADR-0005) — everything after this has to stay a five-second path.
 */
export default function SignIn({ onSignedIn }: Props) {
  const [pin, setPin] = useState('')
  const [attempt, setAttempt] = useState<Attempt>({ status: 'ready' })

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setAttempt({ status: 'submitting' })

    let response: Response
    try {
      response = await fetch('/api/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin }),
      })
    } catch {
      setAttempt({ status: 'refused', reason: 'Die App ist nicht erreichbar.' })
      return
    }

    if (response.ok) {
      onSignedIn()
      return
    }

    // A wrong PIN clears the field rather than leaving it to be corrected: it is four
    // characters, and retyping is faster than finding the mistake.
    setPin('')
    setAttempt({
      status: 'refused',
      reason:
        response.status === 401
          ? 'Das war nicht die PIN.'
          : `Die API hat mit HTTP ${response.status} geantwortet.`,
    })
  }

  return (
    <section className="card">
      <h2>Anmelden</h2>
      <p>Einmal pro Gerät. Danach bleibst du ein Jahr lang angemeldet.</p>
      <form
        className="sign-in"
        onSubmit={(event) => {
          void signIn(event)
        }}
      >
        <label htmlFor="pin">PIN</label>
        <input
          id="pin"
          type="password"
          inputMode="numeric"
          autoComplete="current-password"
          value={pin}
          onChange={(event) => {
            setPin(event.target.value)
          }}
        />
        <button type="submit" disabled={pin === '' || attempt.status === 'submitting'}>
          Weiter
        </button>
      </form>
      {attempt.status === 'refused' && (
        <p className="refused" role="alert">
          {attempt.reason}
        </p>
      )}
    </section>
  )
}
