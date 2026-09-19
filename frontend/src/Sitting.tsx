import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'

import Diary from './Diary.tsx'
import NoConnection from './NoConnection.tsx'
import type { Parent } from './App.tsx'
import {
  askApi,
  Refused,
  reasonFor,
  sendsBackToASignInScreen,
  tellApi,
} from './api.ts'

type Prompt = { id: number; text: string }

/** What the API hands back from the opening draw, from every Answer and from every Skip. */
type Draw = { prompt: Prompt | null }

type State =
  | { status: 'drawing' }
  // `nothingElseLeft` when this Prompt is all the evening has left, which is only ever
  // learnt by skipping it and being given it straight back.
  | { status: 'asking'; prompt: Prompt; nothingElseLeft?: boolean }
  // Answering and skipping are the same wait as far as the screen is concerned: the
  // request is out, and the Prompt on the screen is already spoken for.
  | { status: 'busy'; prompt: Prompt }
  | { status: 'complete' }
  | { status: 'ended' }
  | { status: 'unreachable'; reason: string }

type Props = {
  parent: Parent
  /** How many times the evening notification has been tapped into this app — one
   *  already when the app was opened by the tap itself. The Sitting opens on the Prompt
   *  that notification carried; see `notificationTap.ts`. */
  taps: number
  onRefused: (refusal: Refused) => void
}

/**
 * Why the next opening draw is being made, and which one of them it is.
 *
 * One piece of state because it is one question — "what should be on the screen now, and
 * why?" — asked by two different things: a tap on the notification, and a Parent picking
 * a Sitting up again after ending it.
 */
type Opening = {
  fromTheNotification: boolean
  /** Counted up by every reason to draw again, so that two draws made for the same
   *  reason are still two draws. It is what the effect below is hung on. */
  nth: number
  /** The tap this Sitting has already opened on, against which a new one is noticed. */
  tap: number
}

/** The Prompt the notification showed, or an ordinary draw where there is no longer one
 *  to show (`sitting.py`). The phone never names it; it only says where it came from. */
const AFTER_A_TAP = '/api/prompt?from_the_notification=true'

/**
 * One stretch of answering: a single Prompt, a box, and the next Prompt.
 *
 * Never a form of several questions (ADR-0004). Answering and skipping both return the
 * next Prompt in the same response, so the app moves on in one round trip rather than
 * two — which is the whole difference on a phone at half past ten.
 *
 * Opened from the evening notification, it opens on the Prompt that notification
 * carried rather than on a fresh draw — otherwise the notification asked a question the
 * app then declined to ask. Only the first Prompt: answering or skipping it draws the
 * next one under the ordinary rules, like every other evening.
 *
 * Three ways out, and they are not the same thing. Skipping passes over this Prompt
 * and keeps going; ending the Sitting stops for tonight with the bank still full; and
 * the Diary day being complete is the app running out of questions rather than the
 * Parent running out of evening — the one of the three that leads somewhere, into the
 * Diary the evening's Answers have just been added to.
 */
export default function Sitting({ parent, taps, onRefused }: Props) {
  const [state, setState] = useState<State>({ status: 'drawing' })
  const [text, setText] = useState('')
  // Replaced to ask for a Prompt again, by either of the two things that can want one.
  // Nothing a Parent would recognise is being counted here — the app remembers no
  // Sittings — it is only the handle the draw below is hung on.
  const [opening, setOpening] = useState<Opening>(() => ({
    fromTheNotification: taps > 0,
    nth: 0,
    tap: taps,
  }))
  const box = useRef<HTMLTextAreaElement>(null)
  // The Prompt whatever is in the box was written for. A ref rather than a read of
  // `state`, because it is wanted inside a response that arrives after the render it
  // belongs to: `state` in that closure is whatever it was when the request went out.
  const writtenFor = useRef<number | null>(null)

  const fail = useCallback(
    (error: unknown) => {
      if (sendsBackToASignInScreen(error)) onRefused(error)
      else setState({ status: 'unreachable', reason: reasonFor(error) })
    },
    [onRefused],
  )

  useEffect(() => {
    writtenFor.current = state.status === 'asking' ? state.prompt.id : null
  }, [state])

  // A tap that reached an app which was already open. The Sitting goes back to the
  // notification's Prompt, whatever was on the screen a moment ago: the Parent answered
  // a question on their lock screen, and this is them arriving at it.
  //
  // Adjusted here during the render that brought the tap in, rather than in an effect
  // afterwards: `opening.tap` is the last tap this Sitting acted on, so the comparison
  // is what React calls storing information from previous renders, and doing it in an
  // effect would draw the old Prompt first and replace it a moment later.
  if (opening.tap !== taps) {
    setOpening({ fromTheNotification: true, nth: opening.nth + 1, tap: taps })
  }

  // Runs again when a Sitting is resumed or tapped into, because a draw is not
  // remembered anywhere: asking for one is how the app finds out what is left of the
  // evening.
  useEffect(() => {
    let abandoned = false
    askApi<Draw>(opening.fromTheNotification ? AFTER_A_TAP : '/api/prompt')
      .then(({ prompt }) => {
        if (abandoned) return
        // A tap that lands back on the question already on the screen — the ordinary
        // case, since the notification carried it — has changed nothing, and a sentence
        // half written for it stands. Any other draw has changed the question underneath
        // the box, and what is in it belonged to the question before.
        if (prompt?.id !== writtenFor.current) setText('')
        setState(prompt ? { status: 'asking', prompt } : { status: 'complete' })
      })
      .catch((error: unknown) => {
        if (!abandoned) fail(error)
      })
    return () => {
      abandoned = true
    }
  }, [fail, opening])

  /**
   * Put the Prompt that came back on the screen, with an empty box under it.
   *
   * `passedOver` is the Prompt that was just skipped, when one was: getting it straight
   * back means it is the only thing the evening has left.
   */
  function carryOn(next: Draw, passedOver?: Prompt) {
    setText('')
    setState((current) => {
      // A Sitting the Parent ended while this request was out stays ended. They said so
      // after the tap, and an answer arriving late must not put a question back up.
      if (current.status === 'ended') return current
      if (!next.prompt) return { status: 'complete' }
      return {
        status: 'asking',
        prompt: next.prompt,
        nothingElseLeft: next.prompt.id === passedOver?.id,
      }
    })
    // The next Prompt is already on screen; the keyboard should not have to be
    // summoned again to answer it.
    box.current?.focus()
  }

  /** Leave the Prompt where it was: the request failed, not the Sitting. */
  function backToTheQuestion(prompt: Prompt) {
    setState((current) => (current.status === 'ended' ? current : { status: 'asking', prompt }))
  }

  /**
   * Answered or skipped already — this screen was left open across the four o'clock
   * turn, or another tab got there first. Draw again rather than say so.
   */
  async function afterAStaleScreen() {
    try {
      carryOn(await askApi<Draw>('/api/prompt'))
    } catch (error: unknown) {
      fail(error)
    }
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (state.status !== 'asking') return
    const prompt = state.prompt
    setState({ status: 'busy', prompt })

    try {
      carryOn(await tellApi<Draw>('POST', '/api/answers', { prompt_id: prompt.id, text }))
    } catch (error: unknown) {
      if (error instanceof Refused && error.status === 409) {
        await afterAStaleScreen()
        return
      }
      // What was written stays in the box: the request failed, the sentence did not.
      backToTheQuestion(prompt)
      fail(error)
    }
  }

  async function skipOver() {
    if (state.status !== 'asking') return
    const prompt = state.prompt
    setState({ status: 'busy', prompt })

    try {
      // Whatever was half-written belonged to the Prompt being skipped, so it goes
      // with it rather than following the Parent to the next question.
      carryOn(await tellApi<Draw>('POST', '/api/skips', { prompt_id: prompt.id }), prompt)
    } catch (error: unknown) {
      if (error instanceof Refused && error.status === 409) {
        await afterAStaleScreen()
        return
      }
      backToTheQuestion(prompt)
      fail(error)
    }
  }

  function endTheSitting() {
    // Resuming draws again and rarely lands on the same question, so a half-written
    // sentence is left behind with the Prompt it was for.
    setText('')
    setState({ status: 'ended' })
  }

  if (state.status === 'drawing') {
    return <p className="checking">Einen Moment …</p>
  }

  if (state.status === 'unreachable') {
    return <NoConnection reason={state.reason} />
  }

  if (state.status === 'complete') {
    // Working through the bank leads into the Diary rather than dead-ending on a
    // card: the evening's Answers are in it, and the other Parent's are too.
    return (
      <>
        <section className="card card--good">
          <h2>Für heute ist alles beantwortet</h2>
          <p>Morgen früh um vier gibt es wieder etwas zu erzählen, {parent.name}.</p>
        </section>
        <Diary onRefused={onRefused} />
      </>
    )
  }

  if (state.status === 'ended') {
    return (
      <section className="card">
        <h2>Bis zum nächsten Mal</h2>
        <p>Gute Nacht, {parent.name}. Wenn du doch noch magst, geht es hier weiter.</p>
        <div className="choices">
          <button
            type="button"
            onClick={() => {
              setState({ status: 'drawing' })
              // Picked up by hand, so an ordinary draw — even on an evening whose
              // notification was tapped an hour ago.
              setOpening((before) => ({ ...before, fromTheNotification: false, nth: before.nth + 1 }))
            }}
          >
            Weiterschreiben
          </button>
        </div>
      </section>
    )
  }

  const waiting = state.status === 'busy'

  return (
    <section className="card sitting">
      <p className="prompt">{state.prompt.text}</p>
      {state.status === 'asking' && state.nothingElseLeft && (
        <p className="aside">
          Das ist die letzte Frage für heute — überspringen bringt sie gleich wieder. Beantworte
          sie, oder mach morgen früh weiter.
        </p>
      )}
      <form
        onSubmit={(event) => {
          void save(event)
        }}
      >
        <label className="sr-only" htmlFor="answer">
          Deine Antwort
        </label>
        <textarea
          id="answer"
          ref={box}
          autoFocus
          rows={5}
          value={text}
          onChange={(event) => {
            setText(event.target.value)
          }}
        />
        <div className="actions">
          {/* Quiet, and on the far side from the two buttons that keep the Sitting
              going: ending it is always available and never the thing being urged.
              Not disabled while a request is out either — a Parent who is done is done,
              and `carryOn` knows to leave an ended Sitting alone. */}
          <button type="button" className="quiet" onClick={endTheSitting}>
            Für heute reicht's
          </button>
          <button
            type="button"
            disabled={waiting}
            onClick={() => {
              void skipOver()
            }}
          >
            Überspringen
          </button>
          <button type="submit" disabled={text.trim() === '' || waiting}>
            Speichern
          </button>
        </div>
      </form>
    </section>
  )
}
