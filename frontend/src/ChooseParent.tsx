import { useEffect, useState } from 'react'

import NoConnection from './NoConnection.tsx'
import type { Parent } from './App.tsx'
import { askApi, reasonFor, sendsBackToASignInScreen, tellApi, type Refused } from './api.ts'

type Props = {
  onChosen: (parent: Parent) => void
  onRefused: (refusal: Refused) => void
}

type Choosing =
  | { status: 'reading' }
  | { status: 'ready'; parents: Parent[] }
  | { status: 'unreachable'; reason: string }

/**
 * "Wer schreibt?" — asked once per phone, right after the PIN.
 *
 * The PIN is shared, so it says only that this device has it; the Parent is a claim
 * this screen makes on the device's behalf and the cookie then carries (ADR-0010).
 */
export default function ChooseParent({ onChosen, onRefused }: Props) {
  const [choosing, setChoosing] = useState<Choosing>({ status: 'reading' })
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    let abandoned = false
    askApi<Parent[]>('/api/parents')
      .then((parents) => {
        if (!abandoned) setChoosing({ status: 'ready', parents })
      })
      .catch((error: unknown) => {
        if (abandoned) return
        if (sendsBackToASignInScreen(error)) onRefused(error)
        else setChoosing({ status: 'unreachable', reason: reasonFor(error) })
      })
    return () => {
      abandoned = true
    }
  }, [onRefused])

  async function choose(parent: Parent) {
    setSubmitting(true)
    try {
      await tellApi('PUT', '/api/session/parent', { parent_id: parent.id })
      onChosen(parent)
    } catch (error: unknown) {
      setSubmitting(false)
      if (sendsBackToASignInScreen(error)) onRefused(error)
      else setChoosing({ status: 'unreachable', reason: reasonFor(error) })
    }
  }

  if (choosing.status === 'reading') {
    return <p className="checking">Einen Moment …</p>
  }

  if (choosing.status === 'unreachable') {
    return <NoConnection reason={choosing.reason} />
  }

  return (
    <section className="card">
      <h2>Wer schreibt?</h2>
      <p>Auch das nur einmal pro Gerät. Deine Antworten werden dir zugeordnet.</p>
      <div className="choices">
        {choosing.parents.map((parent) => (
          <button
            key={parent.id}
            type="button"
            disabled={submitting}
            onClick={() => {
              void choose(parent)
            }}
          >
            {parent.name}
          </button>
        ))}
      </div>
    </section>
  )
}
