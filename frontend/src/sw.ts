/**
 * Kidiary's service worker.
 *
 * It does one thing today: keep the app shell on the phone, so that opening Kidiary
 * from the home screen puts something on the screen even where there is no tailnet to
 * reach the Pi through (ADR-0005). What it deliberately does not do is cache anything
 * from the API — a Diary served from last week's cache is a wrong Diary, and it would
 * be wrong silently.
 *
 * It also receives the evening push, puts it on the screen, and opens the app on the
 * Prompt it showed when it is tapped. That is why this file is ours and compiled rather
 * than generated from configuration: ADR-0006 wants that half hand-written, and here it
 * can be written in TypeScript and can import from the rest of `src/` — which is how the
 * tap and the page agree on what a tap is (`notificationTap.ts`).
 *
 * Subscribing is *not* here, which #10 settled: asking for permission needs a user
 * gesture, and reading the VAPID key needs the signed-in fetch, so it lives in the page
 * (`src/push.ts`). ADR-0006's "the push subscription ... written by hand" holds either
 * way — what it rules out is configuration generating that code, not the page owning it.
 */

/// <reference lib="webworker" />

import {
  cleanupOutdatedCaches,
  createHandlerBoundToURL,
  precacheAndRoute,
  type PrecacheEntry,
} from 'workbox-precaching'
import { NavigationRoute, registerRoute } from 'workbox-routing'

import { A_TAP, THE_APP_OPENED_BY_A_TAP } from './notificationTap.ts'

declare const self: ServiceWorkerGlobalScope & {
  // Substituted at build time with every asset Vite emitted, each with its hash.
  __WB_MANIFEST: (string | PrecacheEntry)[]
}

precacheAndRoute(self.__WB_MANIFEST)

// The precache is keyed by content hash, so a deploy leaves the previous build's
// entries behind unless they are swept up.
cleanupOutdatedCaches()

// Take charge of the page that registered us, rather than waiting for the next
// navigation. Without this the very first visit is never served by this worker, so a
// phone that loaded the app once and then lost the tailnet would still get the
// browser's error page. It does not reload anything: that is `skipWaiting`, which is
// not called here on purpose — see the bottom of this file.
self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim())
})

// Asking for a page is answered from the precached shell. React decides what that
// shell shows, and with the API unreachable it shows "Keine Verbindung" — which is
// the truth, and is the app saying it rather than the browser.
registerRoute(
  new NavigationRoute(createHandlerBoundToURL('/index.html'), {
    // Except under /api. Nothing there is a screen, and none of it may be answered
    // from the shell — a JSON request that gets HTML back is the confusing kind of
    // broken. Requests the app makes with `fetch` are not navigations and never reach
    // this route anyway; this is for a phone pointed straight at an API address.
    denylist: [/^\/api\//],
  }),
)

/**
 * What the scheduler sent: a title and the evening's Prompt, as `webpush.py` writes it.
 * The two files are one dataclass and one type, and have to keep saying the same names.
 */
type EveningNotification = { title?: string; body?: string }

/** What to show when the payload is missing or unreadable.
 *
 * A push that shows nothing is not an option: every browser requires a notification for
 * every push — that is the `userVisibleOnly` the subscription promised — and one that
 * stays silent costs the whole subscription. So a push that arrives without a Prompt
 * still says something true, and the app has the question when it is opened. */
const IF_THERE_IS_NO_PROMPT: Required<EveningNotification> = {
  title: 'Kidiary',
  body: 'Eine Frage wartet auf dich.',
}

self.addEventListener('push', (event) => {
  let sent: EveningNotification = {}
  try {
    sent = (event.data?.json() as EveningNotification | undefined) ?? {}
  } catch {
    // Not JSON at all. Nothing to do about it here, and the fallback below is the
    // difference between a strange payload and a lost subscription.
  }

  event.waitUntil(
    self.registration.showNotification(sent.title ?? IF_THERE_IS_NO_PROMPT.title, {
      body: sent.body ?? IF_THERE_IS_NO_PROMPT.body,
      lang: 'de',
      // The home screen icon, so the notification is recognisably from the app that was
      // installed rather than from a website.
      icon: '/icon-192.png',
      badge: '/icon-192.png',
      // One evening, one notification. A tag replaces rather than stacks, so a Parent
      // who was unreachable for a while does not wake up to a column of them.
      tag: 'kidiary-evening',
    }),
  )
})

/**
 * The tap, which is what the whole notification was for: it carried a question, and the
 * app has to open on that question rather than on a fresh one (#12).
 *
 * A phone that is asleep at nine has the app in the background rather than closed, so
 * the usual case is the first one below: there is a window already, and it is focused
 * and told. Opening a second one would leave the Parent looking at an app that had
 * forgotten what they were writing.
 */
self.addEventListener('notificationclick', (event) => {
  // Taking the notification off the lock screen is the tap's first meaning. Done before
  // anything that can fail, so a phone is never left tapping at a dead one.
  event.notification.close()

  event.waitUntil(
    (async () => {
      // `includeUncontrolled`, because a window loaded before this worker took charge is
      // still the app and still the window to open in.
      const [open] = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      if (open) {
        open.postMessage(A_TAP)
        await open.focus()
        return
      }
      await self.clients.openWindow(THE_APP_OPENED_BY_A_TAP)
    })(),
  )
})

// No `skipWaiting`. A new worker waits for the old one to be let go of, so a deploy
// never reloads a Sitting out from under a half-written Answer; `main.tsx` says the
// same thing from the other side.
