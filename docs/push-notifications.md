# Installing it on a phone

Part of [Kidiary](../README.md). How the app installs to a home screen, and how the
evening notification is set, sent, and tapped.

Kidiary is a PWA: opened over https on the tailnet hostname, both phones' browsers offer to add
it to the home screen, and from there it opens as its own app rather than as a browser tab. That
is worth doing for its own sake, and it is also the price of admission for the evening
notification — iOS delivers Web Push only to a web app that has been installed to the home
screen, never to one in a Safari tab.

Nothing about installing works over plain http on a LAN address: a service worker will not
register there, and that is exactly why the app is published through Tailscale Serve (ADR-0005).
To try it from a phone against a laptop-hosted stack, put the laptop on the tailnet too:

```sh
docker compose up --build
tailscale serve --bg 8000        # prints the https://<host>.ts.net URL to open
```

The manifest is written in `frontend/vite.config.ts`. The icons the app serves are the PNGs in
`frontend/public/`, committed rather than generated during the build: every deploy already runs
a Vite build on a 2GB Pi (ADR-0007), and rasterising four icons on it buys nothing a committed
file does not. They are rendered from `frontend/icons/icon.svg` and `icon-maskable.svg`, which
are sources rather than assets and so stay out of `public/`. All three drawings — those two and
`public/favicon.svg` — are the same notebook at three sizes, so a change to one is a change to
all three; re-render at 192, 512, 512 and 180 with any rasteriser.

## Turning on the evening notification

A device is asked once, on the screen it lands on straight after saying which Parent is holding
it, and never by itself again. That timing is the whole point: a permission prompt on load
appears over an app nobody has used yet, gets dismissed, and on iOS there is no second one
without deleting the web app and adding it again. So the app explains what the notification is
for, and the browser's own dialog only comes up after a tap. Afterwards the question waits in
the nav, which also says which way the switch is set — `Erinnerung: an` or `: aus` — so a phone
that is silent is never silently silent.

Permission is per device, and so is a subscription: a Parent carrying a phone and a tablet
switches on twice, and one of them says nothing about the other. The push service's endpoint is
what names a device — unique per device and browser profile — so it is the key the row is stored
under, and a phone registering again updates its row rather than adding one beside it. The app
does register again on every open, which is what repairs a Pi restored from a backup older than
the subscription. Turning it off unsubscribes in the browser first and then deletes the row, and
it stays off: a device with permission but no subscription is reported off rather than quietly
subscribed again.

Nothing here works over plain http, or in a Safari tab on iOS, for the reasons in the section
above. The screen says which of the two is in the way.

## When it comes

One fixed hour for both Parents would land in the middle of one of the two bedtimes, so each
of them sets their own, from under the switch on the same screen. The two settings are not the
same kind of thing and the screen says so: the switch is this phone's, and the hour is this
Parent's — moving it moves it for every device they carry and for none of their partner's.

An hour that has *already gone by* is a Parent saying when their evenings start, not asking to
be woken within the minute. So it counts from the next Diary day, and the screen says as much
rather than leaving them waiting: typing "20:00" at nine in the evening means tomorrow at
eight. An hour still ahead counts tonight — "22:00" typed at nine is being asked at ten.

That is the whole rule (`backend/app/notification_time.py`), and `parents.notification_time_from`
is the column that remembers which of the two was meant. The scheduler cannot work it out from
the time alone: 20:00 looks the same whether it was set a year ago or a minute ago. So the
answer is written down at the moment the Parent says it, and the scheduler only reads it.

## Sending it

The scheduler is its own Compose service running the API's image with a different command
(ADR-0009). It is not a thread inside the API, and must not become one: a scheduler in a
multi-worker API process fires its job once per worker, so both Parents would be woken twice and
the fix would be a lock or a permanent single-worker rule. A second service makes that
impossible rather than something to remember.

Once a minute it asks what is due, and for each Parent whose time has come on the Diary day that
is running:

1. A Delivery for them on this Diary day means the evening is spent, and the pass moves on.
2. A Parent with no Device is passed over **without** a Delivery — switching a phone on at half
   past nine is asking for tonight's notification, and a row written for nobody would have spent
   the evening on nothing.
3. The Prompt is drawn by `draw.py`, the same rule the app draws by (ADR-0004). A notification
   carrying a Prompt the Sitting would not have offered is a notification that lies.
4. **The Delivery is recorded, and committed, before anything is sent.** A scheduler that dies
   between the two costs that Parent one evening; one that sent first and recorded after would,
   on the same crash, wake them a second time with the same question. The second is worse, so
   this is at-most-once on purpose.
5. It is sent to every Device that Parent carries. A Device that fails is a line in the log and
   the next one is still tried; a Parent that fails entirely does not cost the other theirs. A
   Device the push service answers `410 Gone` for is dropped from the table — the subscription
   is finished, and a Device that is still there registers again the next time it is opened.

`sent_at` on the Delivery tells the two apart afterwards: a row with none is an evening that was
claimed and never arrived. Nothing retries it, because by the time anyone looks the evening it
belonged to is over.

The notification asks the push service to hold it only until 04:00, when the Diary day it is
about gives way to the next. A question about today, delivered to a phone that comes back on
tomorrow, has outlived itself.

What goes on the wire is written out in `backend/app/webpush.py` rather than taken from a
library: the body is encrypted to the Device's own keys (RFC 8291) inside the content coding of
RFC 8188, and the request is signed with the private VAPID half (RFC 8292). `test_web_push.py`
holds all of that to RFC 8291's own published example, which is a stronger check than a version
number — a mistake anywhere in the derivation produces different bytes.

Watch an evening go out with:

```sh
docker compose logs -f scheduler
```

## Tapping it

The notification showed a question, so the app opens on that question. Anything else would be
the Diary telling a small untruth in the one place a Parent cannot check, and it would cost the
five-second path: the answer they thought of on the way to the phone would be for a Prompt the
app then declined to ask.

Which question it was is not something the phone remembers. It is the Delivery the scheduler
wrote before it sent anything, so the app asks for it — `GET /api/prompt?from_the_notification=true`
— and the API reads its own record. A phone can say where it came from, never which Prompt it
would like. That request falls back to an ordinary draw wherever opening the delivered one
would be worse: there is no Delivery on this Diary day, the Prompt has been answered since on
the other device, or the tap came the next morning on a notification about an evening that is
over. A Prompt only *skipped* since is still opened — a Skip is a "not now" (ADR-0004), and a
Parent who passed over it at eight and tapped the notification at ten is asking for it back.

Only the first Prompt: answering or skipping it draws the next one under the ordinary rules,
and opening the app by hand starts an ordinary Sitting as it always did.

There are two ways from the tap to the screen, and which one is used is not a choice but
whether the app was still running (`frontend/src/notificationTap.ts`):

- **It was not.** The worker opens a window at `/?erinnerung`, and the app reads the mark off
  its own URL as it starts — once, taking it off in the reading, so that the mark means "this
  open came from a tap" rather than "this window belongs to the notification". Reloading is then
  an ordinary open, and a Parent who has already passed over the delivered Prompt is not handed
  it again by the app restoring itself.
- **It was** — the usual case on a phone, where Kidiary is in the background at nine in the
  evening rather than closed. The worker focuses the window that is already there and posts a
  message into it. Focused rather than navigated, deliberately: a reload would throw away a
  half-written Answer.

## VAPID keys

Web Push has no accounts. A push service accepts a notification for a subscription because the
request is signed by the same key the browser was holding when it subscribed — a P-256 key pair,
public half to the phone, private half kept here. Generate one pair, once:

```sh
docker compose run --rm --no-deps api python -m app.vapid
```

It prints the two lines to paste into `.env`. They are configuration and never reach the
repository or the image, which is built on the Pi itself (ADR-0007) — keep them with the
backups, because replacing either half silently stops every device that has already subscribed.

Leaving them empty is a working state: the stack starts, everything else works, and the app says
notifications are not set up here. Filling them in *wrongly* is not — a malformed key, or two
keys that are not each other's halves, stops the API at startup. That is deliberate. The
alternative is a Parent spending their one permission prompt on a subscription that turns out
months later to have been unsendable.

`VAPID_SUBJECT` belongs to the same rule, and it is the one that actually caught us. RFC 8292
calls it a contact the push service can complain to and requires nobody to check it — so this
repository said, in three places, that nothing verifies it and a real address is politeness.
**Apple verifies it.** A subject it will not accept comes back as `403 {"reason":"BadJwtToken"}`
at the hour the notification was due, against a subscription that is perfectly valid, and the
only trace is one line in the scheduler's log. The default shipped here was
`mailto:kidiary@localhost`, which is precisely such an address, so the first real evening on a
new Pi could not have worked. There is no default now: a stack with keys and no deliverable
contact refuses to start, and `test_vapid.py` holds the rule to the cases that fool it —
`localhost`, a bare hostname, a scheme that is not `mailto:` or `https://`.

It is worth being clear about what that contact *is*, because it looks like a login and is
not: it is an abuse address, so that a push service operator has somebody to complain to
about a sender hammering their infrastructure. Nothing verifies it, nothing is ever sent to
it, and neither the phone nor anybody using the app ever sees it. RFC 8292 allows an
`https:` URL as readily as a `mailto:`, so this repository's own URL does the job without
handing a personal mailbox to Apple and Google, and that is what `.env.example` suggests.
Apple accepts that form: a `https://github.com/...` repository URL was answered
`201 Created` from `web.push.apple.com` on the Pi, which is worth writing down because the specification
allowing something and Apple taking it have already turned out to be different questions
once on this exact claim.

## Offline, and updates

The service worker is `frontend/src/sw.ts`, ours and compiled by `vite-plugin-pwa`, which
injects the list of built assets into it. ADR-0006 said "generated", and carries the refinement
that building it forced: the generated mode leaves nowhere to hand-write the push handling the
same decision asks for. It precaches the app shell — the
HTML, the JS, the CSS, the icons — so opening the app off the tailnet puts Kidiary on the
screen saying it cannot reach the Diary, rather than the browser's own error page.

It caches nothing from `/api`, deliberately. A Diary served from a week-old cache is a wrong
Diary and would be wrong silently, so every API request goes to the network or fails.

A deploy's new worker waits rather than taking over a phone already in the app: a half-written
Answer survives it, and the new version is in charge the next time the app is opened from the
home screen. The *first* worker is the exception — it claims the page that registered it, so a
phone that has loaded the app once is offline-ready without a second visit.
