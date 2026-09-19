import { useCallback, useEffect, useState, type FormEvent } from 'react'

import { askApi, reasonFor, sendsBackToASignInScreen, tellApi, type Refused } from './api.ts'

/** When this Parent is asked, and whether that is still to come tonight (`app/push.py`). */
type TheTime = { time: string; counts_tonight: boolean }

type Props = {
  onRefused: (refusal: Refused) => void
}

/**
 * The hour this Parent's evening notification arrives at.
 *
 * It sits under the on/off switch on the same screen, and the difference between the two
 * is the thing this section has to make plain: the switch is this phone's, and the hour
 * is this Parent's — it moves for every device they carry, and for none of their
 * partner's. Two people with one bedtime routine between them do not have one evening,
 * which is the whole reason the hour is not a setting in `.env`.
 *
 * An hour that has already gone by is a Parent saying when their evenings start rather
 * than asking to be notified within the minute, so the API counts it from tomorrow and
 * says so; this screen passes that on, because a Parent who was not told would sit
 * waiting for a notification that is a day away.
 */
export default function NotificationTime({ onRefused }: Props) {
  // What the API last said, and what is in the box. They differ exactly while a Parent
  // has typed something and not saved it, which is what the save button is lit by.
  const [saved, setSaved] = useState<TheTime | null>(null)
  const [chosen, setChosen] = useState('')
  const [busy, setBusy] = useState(false)
  const [trouble, setTrouble] = useState<string | null>(null)

  const fail = useCallback(
    (error: unknown) => {
      if (sendsBackToASignInScreen(error)) onRefused(error)
      else setTrouble(reasonFor(error))
    },
    [onRefused],
  )

  useEffect(() => {
    let abandoned = false
    askApi<TheTime>('/api/notification-time')
      .then((answered) => {
        if (abandoned) return
        setSaved(answered)
        setChosen(answered.time)
      })
      .catch((error: unknown) => {
        if (!abandoned) fail(error)
      })
    return () => {
      abandoned = true
    }
    // Asked once per visit to this screen: nobody but this Parent can move the hour,
    // and there is nothing for it to go stale against.
  }, [fail])

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setTrouble(null)
    try {
      const answered = await tellApi<TheTime>('PUT', '/api/notification-time', { time: chosen })
      setSaved(answered)
      // From the API rather than from the box: it is the same hour, to the minute the
      // scheduler works in, and taking it back is what makes "saved" mean saved.
      setChosen(answered.time)
    } catch (error: unknown) {
      fail(error)
    } finally {
      setBusy(false)
    }
  }

  if (saved === null) {
    return <p className="checking">{trouble ?? 'Einen Moment …'}</p>
  }

  const unsaved = chosen !== saved.time

  return (
    <section className="card">
      <h2>Wann soll gefragt werden?</h2>
      <p>
        Die Uhrzeit gilt für dich — auf allen deinen Geräten. Für deinen Partner ändert sich
        dadurch nichts; er stellt seine eigene ein.
      </p>
      <form className="notification-time" onSubmit={(event) => void save(event)}>
        <label className="sr-only" htmlFor="notification-time">
          Uhrzeit der abendlichen Frage
        </label>
        <input
          id="notification-time"
          type="time"
          required
          value={chosen}
          onChange={(event) => {
            setChosen(event.target.value)
          }}
        />
        <button type="submit" disabled={busy || !unsaved}>
          Speichern
        </button>
      </form>
      {!unsaved && !saved.counts_tonight && (
        <p className="aside">
          Für heute ist {saved.time} Uhr schon vorbei — die nächste Frage kommt morgen Abend.
        </p>
      )}
      {trouble && <p className="aside">{trouble}</p>}
    </section>
  )
}
