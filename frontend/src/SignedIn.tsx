import { useCallback, useEffect, useState } from 'react'

import Diary from './Diary.tsx'
import Notifications from './Notifications.tsx'
import Sitting from './Sitting.tsx'
import type { Parent } from './App.tsx'
import type { Refused } from './api.ts'
import {
  openedByATap,
  rememberTheQuestionWasPut,
  runningAsAnInstalledApp,
  theQuestionWasAlreadyPut,
  useNotifications,
  whenTapped,
  type NotificationState,
} from './push.ts'

/** The three things a signed-in Parent can be doing: writing, reading back, or
 *  deciding whether this device wakes them in the evening. */
type View = 'sitting' | 'diary' | 'notifications'

type Props = {
  parent: Parent
  /** True when this device has just said who is holding it, and has never been asked
   *  about notifications. */
  justClaimed: boolean
  onRefused: (refusal: Refused) => void
}

const NAMES: Record<View, string> = {
  sitting: 'Schreiben',
  diary: 'Tagebuch lesen',
  notifications: 'Erinnerung',
}

/**
 * Everything behind the PIN and the Parent claim.
 *
 * A new device opens on the notification question rather than on a Prompt. It is the
 * one moment where asking makes sense — the phone is being set up, the person is
 * paying attention, and the app has just introduced itself — and after it the question
 * is never pushed again, only waiting in the nav.
 *
 * It is also where a tap on the evening notification lands, because a tap has to be able
 * to reach the Sitting from anywhere — including from the Diary, which is where a Parent
 * who opened the app an hour earlier was probably left.
 */
export default function SignedIn({ parent, justClaimed, onRefused }: Props) {
  const [view, setView] = useState<View>(justClaimed ? 'notifications' : 'sitting')
  // One already when the app itself was opened by the tap. Counted rather than flagged,
  // so that a second tap an hour later is a second thing that happened rather than the
  // same `true` it already was.
  const [taps, setTaps] = useState(() => (openedByATap() ? 1 : 0))
  // True only until this device has been past the question once. After that the
  // notification screen is somewhere a Parent went on purpose, and offering them a way
  // onwards to a Prompt they did not ask for would be the app talking over them.
  const [onboarding, setOnboarding] = useState(justClaimed)
  /**
   * Put the question to a device that has never had it put.
   *
   * An iPhone signed in in Safari and *then* added to the home screen opens the
   * installed app already signed in: it never goes through the claim, so it would never
   * be asked, and the only trace of the whole feature would be a word in the nav. That
   * is the silent loss this ticket was written about, and it shows on a phone rather
   * than on a desktop. Asked once here, remembered for this device, and never put again
   * whatever it is answered — allowing or refusing both leave the browser with a record,
   * which is what `neverAsked` reads.
   */
  const putTheQuestion = useCallback(() => {
    if (!runningAsAnInstalledApp() || theQuestionWasAlreadyPut()) return
    rememberTheQuestionWasPut()
    setOnboarding(true)
    setView('notifications')
  }, [])

  // A tap that found the app already open: it is sent here by `sw.ts` rather than
  // opening a window, so that a half-written Answer survives being tapped at.
  useEffect(
    () =>
      whenTapped(() => {
        setTaps((before) => before + 1)
        setView('sitting')
      }),
    [],
  )

  // Owned here rather than inside the screen, so the nav can say which way the switch
  // is set without the Parent having to go and look.
  const notifications = useNotifications(onRefused, justClaimed ? undefined : putTheQuestion)

  const elsewhere = (Object.keys(NAMES) as View[]).filter((somewhere) => somewhere !== view)

  return (
    <>
      <nav>
        {elsewhere.map((somewhere) => (
          <button
            key={somewhere}
            type="button"
            className="quiet"
            onClick={() => {
              setView(somewhere)
            }}
          >
            {NAMES[somewhere]}
            {somewhere === 'notifications' && switchPosition(notifications.state)}
          </button>
        ))}
      </nav>

      {/* Hidden rather than unmounted: a half-written sentence has to survive a look
          at the Diary, and coming back must not draw a different Prompt. */}
      <div hidden={view !== 'sitting'}>
        <Sitting parent={parent} taps={taps} onRefused={onRefused} />
      </div>

      {/* Mounted afresh each time, so the Diary opens on what was written a moment
          ago rather than on what was there when the app started. */}
      {view === 'diary' && <Diary onRefused={onRefused} />}

      {view === 'notifications' && (
        <Notifications
          {...notifications}
          offerAWayOnwards={onboarding}
          onRefused={onRefused}
          onDone={() => {
            // Going on to a Prompt is an answer of sorts: the question was put and left
            // for later, so it is not put again unprompted on this device.
            rememberTheQuestionWasPut()
            setOnboarding(false)
            setView('sitting')
          }}
        />
      )}
    </>
  )
}

/**
 * The one word the nav adds, so that "off" is something the app says rather than
 * something a Parent finds out in three weeks by never being asked anything.
 *
 * Silent while the answer is still being worked out, and where the device could not
 * be subscribed even in principle — there is no switch to report the position of.
 */
function switchPosition(state: NotificationState): string {
  if (state.status === 'on') return ': an'
  if (state.status === 'off' || state.status === 'blocked') return ': aus'
  return ''
}
