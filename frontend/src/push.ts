/**
 * Whether this device gets the evening notification, and the two taps that change it.
 *
 * Everything here is deliberately driven by a tap. Asking for permission on load is
 * how the whole feature gets lost: the dialog appears over an app nobody has used yet,
 * it is dismissed, and on iOS there is no second one without deleting the web app and
 * installing it again. So the question is asked on a screen that has already explained
 * what it is for (`Notifications.tsx`), and never before.
 *
 * What the app reports is what is true on *this* device. A Parent has as many devices
 * as they carry (`CONTEXT.md`), each subscribes separately, and one phone having
 * notifications on says nothing about the other.
 *
 * Subscribing lives here rather than in `sw.ts` because it needs two things the worker
 * has not got: a user gesture for the permission prompt, and the signed-in fetch that
 * reads the VAPID key. What stays the worker's is receiving a push and catching the tap
 * on it; the two ways that tap reaches this side are at the bottom of this file, and what
 * a tap *is* is `notificationTap.ts`.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { askApi, reasonFor, sendsBackToASignInScreen, tellApi, type Refused } from './api.ts'
import { A_TAP, THE_MARK } from './notificationTap.ts'

export type NotificationState =
  | { status: 'checking' }
  /** No Push API here at all. On iOS that means a Safari tab rather than the home screen. */
  | { status: 'unsupported' }
  /** Push is there, but no service worker is running to receive it — see `theWorker`. */
  | { status: 'no-worker' }
  /** This Pi has no VAPID keys, so there is nothing to subscribe to (`app/vapid.py`). */
  | { status: 'unconfigured' }
  /** Off, and can be turned on. `dismissed` when the browser's dialog was closed
   *  unanswered; `neverAsked` when the browser has no record of being asked at all,
   *  which is what `SignedIn.tsx` needs to know whether to put the question. */
  | { status: 'off'; dismissed?: boolean; neverAsked?: boolean }
  /** Refused at the browser level. Only the phone's own settings can undo this. */
  | { status: 'blocked' }
  | { status: 'on' }
  | { status: 'failed'; reason: string }

/** How long to wait for a service worker before deciding there is none. */
const WORKER_TIMEOUT = 4000

type PushKey = { public_key: string | null }

function thisBrowserCanBeSubscribed(): boolean {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
}

/**
 * The worker that would receive a push, or nothing.
 *
 * `navigator.serviceWorker.ready` never settles where no worker was ever registered,
 * which is exactly the case in `npm run dev` — the worker is only built by
 * `npm run build`. So it is raced against a clock rather than awaited outright.
 */
async function theWorker(): Promise<ServiceWorkerRegistration | null> {
  const registered = await navigator.serviceWorker.getRegistration()
  if (registered) return registered

  return await Promise.race([
    navigator.serviceWorker.ready,
    new Promise<null>((giveUp) => {
      setTimeout(() => {
        giveUp(null)
      }, WORKER_TIMEOUT)
    }),
  ])
}

/** Everything a subscription needs, or the screen explaining why there will not be one. */
type Subscribable =
  | { can: false; why: NotificationState }
  | { can: true; registration: ServiceWorkerRegistration; key: string }

/**
 * The three things that have to be true before this device can subscribe at all.
 *
 * Asked again on the tap rather than remembered from the open: that is one more GET of
 * a key which rarely changes, set against a Parent waiting for a tap to do something,
 * and it buys both paths below a single account of what "ready" means.
 */
async function whatItTakesToSubscribe(): Promise<Subscribable> {
  if (!thisBrowserCanBeSubscribed()) return { can: false, why: { status: 'unsupported' } }

  const { public_key } = await askApi<PushKey>('/api/push/key')
  if (!public_key) return { can: false, why: { status: 'unconfigured' } }

  const registration = await theWorker()
  if (!registration) return { can: false, why: { status: 'no-worker' } }

  return { can: true, registration, key: public_key }
}

/**
 * The VAPID public key as bytes.
 *
 * It travels as base64url because that is what every Web Push library and `.env`
 * speak; `applicationServerKey` wants the 65 bytes behind it.
 */
function asBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const padded = base64url.padEnd(base64url.length + ((4 - (base64url.length % 4)) % 4), '=')
  const binary = atob(padded.replace(/-/g, '+').replace(/_/g, '/'))
  // Filled by hand rather than with `Uint8Array.from`, which is typed over any buffer
  // — including the shared one, which `applicationServerKey` will not take.
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index)
  }
  return bytes
}

function asBase64url(bytes: Uint8Array): string {
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

/**
 * Whether this subscription was made for the key the Pi is holding now.
 *
 * A subscription is bound to the key it was created with, so replacing the pair in
 * `.env` leaves every existing one undeliverable — `docs/push-notifications.md` says as
 * much. A phone
 * cannot be told that happened, but it can notice, and that is the difference between
 * wrongly saying "an" for months and repairing it on the next open.
 */
function madeForTheCurrentKey(subscription: PushSubscription, key: string): boolean {
  const subscribedWith = subscription.options.applicationServerKey
  return subscribedWith !== null && asBase64url(new Uint8Array(subscribedWith)) === key
}

/** How long a push service gets to hand over a subscription before the tap gives up. */
const SUBSCRIBE_TIMEOUT = 15000

class ThePushServiceDidNotAnswer extends Error {
  constructor() {
    super('Der Push-Dienst des Browsers hat nicht geantwortet. Versuch es noch einmal.')
    this.name = 'ThePushServiceDidNotAnswer'
  }
}

/**
 * Ask the push service for a subscription, and do not wait forever.
 *
 * `pushManager.subscribe()` has no timeout of its own and was observed hanging past
 * twenty seconds, which left the button greyed out and the screen saying nothing. That
 * is the worst thing this screen can do: the one tap the whole feature depends on
 * appears to do nothing at all, and a Parent who taps it twice is a Parent who thinks
 * the app is broken. A deadline turns it into a sentence they can act on.
 *
 * A subscription that arrives after the deadline is not lost: the next open finds it in
 * the browser and sends it on, which is the same repair as a Pi that lost the row.
 */
async function subscribe(
  registration: ServiceWorkerRegistration,
  key: string,
): Promise<PushSubscription> {
  let deadline: ReturnType<typeof setTimeout> | undefined
  try {
    return await Promise.race([
      registration.pushManager.subscribe({
        // Required by every browser: a push must show the person something. It is also
        // what this app wants — the notification carries the evening's Prompt.
        userVisibleOnly: true,
        applicationServerKey: asBytes(key),
      }),
      new Promise<never>((_, giveUp) => {
        deadline = setTimeout(() => {
          giveUp(new ThePushServiceDidNotAnswer())
        }, SUBSCRIBE_TIMEOUT)
      }),
    ])
  } finally {
    clearTimeout(deadline)
  }
}

/** Tell the API about this device. Sent as the browser handed it over. */
async function tellTheApi(subscription: PushSubscription): Promise<void> {
  await tellApi('PUT', '/api/push/subscription', subscription.toJSON())
}

/**
 * Let go of a subscription, in both of the places that know about it.
 *
 * The browser first, because once it has let go the row is all that is left — and a row
 * nothing can reach is one the scheduler pushes into and is answered 410.
 */
async function forget(subscription: PushSubscription): Promise<void> {
  const { endpoint } = subscription
  await subscription.unsubscribe()
  await tellApi('DELETE', '/api/push/subscription', { endpoint })
}

/**
 * What this device is set to right now, asked at every open.
 *
 * An existing subscription is re-sent rather than assumed to be on record: a Pi
 * restored from a backup older than the subscription would otherwise never push to a
 * phone that believes it is subscribed, and nothing would ever say so.
 *
 * A device with permission but no subscription is reported off rather than quietly
 * subscribed again. Permission outlives being turned off here — the browser keeps the
 * grant — so re-subscribing on sight would undo the off switch every time the app
 * opened, which is the one thing an off switch may not do.
 */
async function whatThisDeviceIsSetTo(): Promise<NotificationState> {
  const needed = await whatItTakesToSubscribe()
  if (!needed.can) return needed.why

  const subscription = await needed.registration.pushManager.getSubscription()

  if (Notification.permission === 'denied') {
    // Refused in the phone's own settings, after this device had once said yes. Nothing
    // can be delivered to it any more, so the subscription goes now rather than sitting
    // in the table looking like a Parent who has notifications on.
    if (subscription) await forget(subscription)
    return { status: 'blocked' }
  }

  if (!subscription) {
    return { status: 'off', neverAsked: Notification.permission === 'default' }
  }

  if (!madeForTheCurrentKey(subscription, needed.key)) {
    // The Pi's pair was replaced. Exchanged rather than merely reported: this device did
    // ask to be notified and the permission still stands, so nobody is asked anything —
    // it is the same repair as re-sending a subscription the Pi has lost.
    await forget(subscription)
    await tellTheApi(await subscribe(needed.registration, needed.key))
    return { status: 'on' }
  }

  await tellTheApi(subscription)
  return { status: 'on' }
}

/** The installed app rather than a browser tab. */
export function runningAsAnInstalledApp(): boolean {
  // `display-mode` is the standard; `navigator.standalone` is how iOS has always said
  // it, and iOS is the platform this distinction actually decides anything on.
  const standalone = (navigator as { standalone?: boolean }).standalone === true
  return standalone || window.matchMedia('(display-mode: standalone)').matches
}

//: Per device, per browser. Losing it costs one extra offer, which is why it can live
//: in storage that a private window or a cleared cache may simply not have.
const THE_QUESTION_WAS_PUT = 'kidiary.notifications.offered'

export function theQuestionWasAlreadyPut(): boolean {
  try {
    return localStorage.getItem(THE_QUESTION_WAS_PUT) !== null
  } catch {
    // Storage a browser refuses to hand over reads as "not yet", which offers the
    // question again rather than silently never asking.
    return false
  }
}

export function rememberTheQuestionWasPut(): void {
  try {
    localStorage.setItem(THE_QUESTION_WAS_PUT, 'yes')
  } catch {
    // Nothing to do about it, and nothing worth a screen: the cost is being asked twice.
  }
}

export type NotificationSwitch = {
  state: NotificationState
  /** A request is out. Both taps are slow enough on a phone to be worth saying so. */
  busy: boolean
  turnOn: () => void
  turnOff: () => void
}

/**
 * @param onRefused   the cookie was refused, which is a screen the shell owns.
 * @param onNeverAsked this device turns out to have no record of ever being asked. Said
 *   once per settle, and only the shell knows whether that is worth acting on.
 */
export function useNotifications(
  onRefused: (refusal: Refused) => void,
  onNeverAsked?: () => void,
): NotificationSwitch {
  const [state, setState] = useState<NotificationState>({ status: 'checking' })
  const [busy, setBusy] = useState(false)
  //: A tap is in flight and owns the state. iOS may hide the page while its permission
  //: dialog is up, so the re-check below can fire in the middle of one.
  const tapping = useRef(false)

  const fail = useCallback(
    (error: unknown) => {
      if (sendsBackToASignInScreen(error)) onRefused(error)
      else setState({ status: 'failed', reason: reasonFor(error) })
    },
    [onRefused],
  )

  useEffect(() => {
    let abandoned = false

    /**
     * Ask again what this device is set to.
     *
     * `quietly` is for the re-check on resume, where a failure is not news: a phone that
     * wakes up off the tailnet must not have a true "an" replaced by "Keine Verbindung".
     * A refused cookie still counts, because that is a screen rather than a hiccup.
     */
    const settle = (quietly: boolean) => {
      if (tapping.current) return
      whatThisDeviceIsSetTo()
        .then((settled) => {
          if (abandoned || tapping.current) return
          setState(settled)
          if (settled.status === 'off' && settled.neverAsked) onNeverAsked?.()
        })
        .catch((error: unknown) => {
          if (abandoned) return
          if (sendsBackToASignInScreen(error)) onRefused(error)
          else if (!quietly) setState({ status: 'failed', reason: reasonFor(error) })
        })
    }

    settle(false)

    // A phone resumes an app far more often than it starts one, and iOS does not update
    // `Notification.permission` in a suspended page: revoking notifications in
    // Einstellungen left Kidiary still saying "an" until it was cold-started. Verified on
    // an iPhone, which is the only place it shows. Asking again on the way back is the
    // whole fix, and it covers every other way the answer goes stale while away —
    // a subscription the browser dropped, or keys replaced on the Pi.
    const whenBackOnScreen = () => {
      if (document.visibilityState === 'visible') settle(true)
    }
    document.addEventListener('visibilitychange', whenBackOnScreen)

    return () => {
      abandoned = true
      document.removeEventListener('visibilitychange', whenBackOnScreen)
    }
  }, [fail, onRefused, onNeverAsked])

  const turnOn = useCallback(() => {
    setBusy(true)
    tapping.current = true
    void (async () => {
      try {
        // iOS only accepts this inside a gesture, and a gesture does not survive an
        // await — which is why it is the first thing that happens here.
        const permission = await Notification.requestPermission()
        if (permission === 'denied') {
          setState({ status: 'blocked' })
          return
        }
        if (permission !== 'granted') {
          // Closed without answering. The grant was not spent, so asking again works —
          // which is worth saying, because it is the one refusal that is recoverable.
          setState({ status: 'off', dismissed: true })
          return
        }

        const needed = await whatItTakesToSubscribe()
        if (!needed.can) {
          setState(needed.why)
          return
        }

        let subscription = await needed.registration.pushManager.getSubscription()
        if (subscription && !madeForTheCurrentKey(subscription, needed.key)) {
          await forget(subscription)
          subscription = null
        }
        subscription ??= await subscribe(needed.registration, needed.key)

        await tellTheApi(subscription)
        setState({ status: 'on' })
      } catch (error: unknown) {
        fail(error)
      } finally {
        tapping.current = false
        setBusy(false)
      }
    })()
  }, [fail])

  const turnOff = useCallback(() => {
    setBusy(true)
    tapping.current = true
    void (async () => {
      try {
        const registration = await theWorker()
        if (!registration) {
          // Nothing here to unsubscribe, and nothing that could have sent the DELETE.
          // Saying "aus" would be claiming a row was cleared that nobody asked about, so
          // the screen says what is actually the matter instead.
          setState({ status: 'no-worker' })
          return
        }

        const subscription = await registration.pushManager.getSubscription()
        if (subscription) await forget(subscription)
        setState({ status: 'off' })
      } catch (error: unknown) {
        fail(error)
      } finally {
        tapping.current = false
        setBusy(false)
      }
    })()
  }, [fail])

  return { state, busy, turnOn, turnOff }
}


//: Read once and remembered. The mark comes off the URL as it is read, and React asks
//: twice in development — so the answer, not the URL, is what a second caller gets.
let thisAppWasOpenedByATap: boolean | null = null

/**
 * Whether this open came from tapping the evening notification.
 *
 * The mark is taken off the URL in the reading of it, which is what makes it mean "this
 * open came from a tap" rather than "this window belongs to the notification". A reload
 * is then an ordinary open: a Parent who has already passed over the delivered Prompt is
 * not handed it again by the app restoring itself, and a Sitting picked up tomorrow on a
 * window that was never closed starts where a Sitting starts.
 */
export function openedByATap(): boolean {
  thisAppWasOpenedByATap ??= theMarkTakenOffTheUrl()
  return thisAppWasOpenedByATap
}

function theMarkTakenOffTheUrl(): boolean {
  const here = new URL(window.location.href)
  if (!here.searchParams.has(THE_MARK)) return false

  here.searchParams.delete(THE_MARK)
  // Replaced rather than pushed: the marked URL is not a place to go back to.
  window.history.replaceState(null, '', `${here.pathname}${here.search}${here.hash}`)
  return true
}

/**
 * Hear a tap that arrived while the app was already open, the case a phone is nearly
 * always in: Kidiary is in the background at nine in the evening rather than closed.
 *
 * Returns the way to stop listening, which is what a React effect wants back. Silent
 * where there is no service worker at all — `npm run dev`, or a browser that could not
 * receive a push in the first place — because nothing there could ever tap.
 */
export function whenTapped(reopen: () => void): () => void {
  if (!('serviceWorker' in navigator)) return () => {}

  const listen = (event: MessageEvent) => {
    if (event.data === A_TAP) reopen()
  }
  navigator.serviceWorker.addEventListener('message', listen)
  return () => {
    navigator.serviceWorker.removeEventListener('message', listen)
  }
}
