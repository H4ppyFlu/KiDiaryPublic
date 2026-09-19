/**
 * What a tap on the evening notification is, agreed between two things that never run
 * in the same place.
 *
 * `sw.ts` is woken by the tap and has no DOM; the page has a DOM and is asleep or not
 * running at all. There are two ways across, and which one is used is not a choice — it
 * is whether the app was still open:
 *
 * - **It was not.** The worker opens a window at `THE_APP_OPENED_BY_A_TAP`, and the app
 *   reads the mark off its own URL as it starts (`openedByATap` in `push.ts`).
 * - **It was.** A window is already there — the usual case on a phone, where the app is
 *   in the background rather than closed — so the worker focuses it and posts `A_TAP`
 *   into it (`whenTapped`). Focused rather than navigated, deliberately: a reload would
 *   throw away a half-written Answer, which is the one thing this app tries hardest
 *   never to do.
 *
 * Only the two words are here. Everything either side does with them needs a DOM or a
 * worker and so lives where it belongs, which is also why this file has no imports and
 * touches nothing: it is compiled into both projects (`tsconfig.app.json`,
 * `tsconfig.sw.json`), and anything platform-shaped in it would be a type error in one
 * of the two.
 *
 * Neither word carries the Prompt. Which question the notification showed is the
 * Delivery the scheduler wrote before it sent anything, and the app asks the API for it
 * (`GET /api/prompt?from_the_notification=true`) rather than being told by the phone. A
 * tap says only: you were opened from this evening's notification.
 */

/** The mark on the URL, as a query a person could read over a shoulder. */
export const THE_MARK = 'erinnerung'

/** Where the worker opens the app when there is no window to focus. */
export const THE_APP_OPENED_BY_A_TAP = `/?${THE_MARK}`

/** What the worker posts into a window that is already open. */
export const A_TAP = 'kidiary:tapped-the-notification'
