import { useCallback, useEffect, useState } from 'react'

import ChooseParent from './ChooseParent.tsx'
import NoConnection from './NoConnection.tsx'
import SignIn from './SignIn.tsx'
import SignedIn from './SignedIn.tsx'
import { askApi, Refused, reasonFor } from './api.ts'
import './App.css'

export type Parent = { id: number; position: number; name: string }

type Access =
  | { status: 'asking' }
  | { status: 'signed-out' }
  | { status: 'unclaimed' }
  // `justClaimed` when the Parent was picked a moment ago rather than a year ago: it
  // is the one moment where the app asks about notifications by itself.
  | { status: 'signed-in'; parent: Parent; justClaimed: boolean }
  | { status: 'unreachable'; reason: string }

export default function App() {
  const [access, setAccess] = useState<Access>({ status: 'asking' })

  // The cookie is HttpOnly, so only the API can say what this device is signed in as,
  // and every answer it gives is a screen: a 401 puts up the PIN, a null Parent puts
  // up "wer schreibt?", and a Parent opens the Sitting.
  useEffect(() => {
    let abandoned = false
    askApi<{ parent: Parent | null }>('/api/session')
      .then(({ parent }) => {
        if (!abandoned) {
          setAccess(
            parent
              ? { status: 'signed-in', parent, justClaimed: false }
              : { status: 'unclaimed' },
          )
        }
      })
      .catch((error: unknown) => {
        if (abandoned) return
        setAccess(
          error instanceof Refused && error.status === 401
            ? { status: 'signed-out' }
            : { status: 'unreachable', reason: reasonFor(error) },
        )
      })
    return () => {
      abandoned = true
    }
  }, [])

  // The same rule, applied again when a screen already on the phone is refused: the
  // year runs out mid-Sitting, or the database loses the Parent the cookie names.
  // Everything behind the claim unmounts with it, so signing in again opens on the
  // Sitting: the app is for answering, and the Diary is somewhere you go rather than
  // somewhere you are left.
  const sendBack = useCallback((refusal: Refused) => {
    setAccess(refusal.status === 401 ? { status: 'signed-out' } : { status: 'unclaimed' })
  }, [])

  return (
    <main>
      <h1>Kidiary</h1>
      {access.status === 'signed-in' && (
        <p className="subtitle">Guten Abend, {access.parent.name}.</p>
      )}

      {access.status === 'asking' && <p className="checking">Einen Moment …</p>}

      {access.status === 'signed-out' && (
        <SignIn
          onSignedIn={() => {
            setAccess({ status: 'unclaimed' })
          }}
        />
      )}

      {access.status === 'unclaimed' && (
        <ChooseParent
          onChosen={(parent) => {
            setAccess({ status: 'signed-in', parent, justClaimed: true })
          }}
          onRefused={sendBack}
        />
      )}

      {access.status === 'signed-in' && (
        <SignedIn
          parent={access.parent}
          justClaimed={access.justClaimed}
          onRefused={sendBack}
        />
      )}

      {access.status === 'unreachable' && <NoConnection reason={access.reason} />}
    </main>
  )
}
