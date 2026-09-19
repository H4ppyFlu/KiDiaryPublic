import { useEffect, useState } from 'react'

import NoConnection from './NoConnection.tsx'
import type { Parent } from './App.tsx'
import { askApi, reasonFor, sendsBackToASignInScreen, type Refused } from './api.ts'

type Age = { years: number; months: number; label: string }

type Entry = { id: number; prompt: string; author: Parent; text: string }

/** One evening: both Parents' Answers, and how old the Child was that day. */
type Day = { diary_day: string; age: Age; answers: Entry[] }

type Reading =
  | { status: 'reading' }
  | { status: 'read'; days: Day[] }
  | { status: 'unreachable'; reason: string }

type Props = {
  onRefused: (refusal: Refused) => void
}

const asAGermanDate = new Intl.DateTimeFormat('de-DE', {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
  year: 'numeric',
})

/**
 * A Diary day is a plain date rather than a moment, so it is read as one.
 *
 * `new Date('2026-05-12')` is midnight UTC, which is still the 11th in half the world;
 * building the date from its parts keeps the evening on the day it was written.
 */
function theEvening(diaryDay: string): string {
  const [year, month, day] = diaryDay.split('-').map(Number)
  return asAGermanDate.format(new Date(year, month - 1, day))
}

/**
 * The Diary: everything both Parents have written, newest evening first.
 *
 * One archive rather than two (ADR-0001) — the point of reading it is the part of the
 * day you were not there for, so the Answers are interleaved under the evening they
 * belong to rather than sorted by who wrote them. The Child's age labels the evening
 * rather than each sentence in it (ADR-0002): it is a fact about the day, and repeating
 * it under every Answer would say the same thing five times.
 *
 * Mounted afresh each time the Diary is opened, so it shows what was written a moment
 * ago rather than what was there when the app started.
 */
export default function Diary({ onRefused }: Props) {
  const [reading, setReading] = useState<Reading>({ status: 'reading' })

  useEffect(() => {
    let abandoned = false
    askApi<{ days: Day[] }>('/api/diary')
      .then(({ days }) => {
        if (!abandoned) setReading({ status: 'read', days })
      })
      .catch((error: unknown) => {
        if (abandoned) return
        if (sendsBackToASignInScreen(error)) onRefused(error)
        else setReading({ status: 'unreachable', reason: reasonFor(error) })
      })
    return () => {
      abandoned = true
    }
  }, [onRefused])

  if (reading.status === 'reading') {
    return <p className="checking">Einen Moment …</p>
  }

  if (reading.status === 'unreachable') {
    return <NoConnection reason={reading.reason} />
  }

  // The ordinary state of the first evening, and of every evening until somebody
  // writes something. It is not a failure and must not look like one.
  if (reading.days.length === 0) {
    return (
      <section className="card">
        <h2>Noch nichts aufgeschrieben</h2>
        <p>Die erste Antwort steht heute Abend hier.</p>
      </section>
    )
  }

  return (
    <div className="diary">
      {reading.days.map((day) => (
        <section key={day.diary_day} className="day">
          <h2>{theEvening(day.diary_day)}</h2>
          <p className="age">{day.age.label} alt</p>
          {day.answers.map((entry) => (
            <article key={entry.id} className="entry">
              <p className="asked">{entry.prompt}</p>
              <p className="written">{entry.text}</p>
              <p className="by">{entry.author.name}</p>
            </article>
          ))}
        </section>
      ))}
    </div>
  )
}
