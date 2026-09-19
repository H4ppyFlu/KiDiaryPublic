# Kidiary

A private, shared diary about one child, kept by both parents. Each evening the app asks a
short question and each parent answers as many as they feel like in one sitting; the answers
accumulate into an archive of the child's growing up.

It runs on a Raspberry Pi at home and is published to the family's tailnet and to nowhere
else. The vocabulary this project speaks is in [`CONTEXT.md`](CONTEXT.md), and the decisions
behind it in [`docs/adr/`](docs/adr).

## The stack

| | |
| --- | --- |
| **API** | Python 3.13, FastAPI, SQLAlchemy 2, Alembic, Pydantic Settings |
| **Database** | Postgres 17 |
| **Frontend** | React 19, TypeScript, Vite, an installable PWA with a hand-written service worker |
| **Push** | Web Push built straight onto RFC 8188, 8291 and 8292 rather than onto a library |
| **Tests** | pytest, driving the API over HTTP against a real Postgres |
| **Runtime** | Docker Compose, a multi-stage build, four containers on a Raspberry Pi 4 |
| **Network** | Tailscale Serve, for a browser-trusted https origin with no public exposure |

## Status

The app asks, answers, skips and reads back. The stack comes up, migrates itself and seeds one
Child, two Parents and the twenty Prompts; a phone is asked for the PIN and for which Parent is
holding it, once each, and then stays signed in for a year. It installs to a home screen and
opens without browser chrome, and it opens even with no way to reach the Pi. Each Parent sets
what time their evening notification arrives, and every evening a second container wakes both
of them once each with a real question — which is the question the app opens on when that
notification is tapped. Every night, a quarter of an hour after the Diary day turns over, the
whole thing is dumped to a file that has been restored once to prove it can be.

## Running the stack

The only prerequisite is Docker with Compose. Copy `.env.example` to `.env` and set `PIN` and
`SESSION_SECRET`; the API refuses to start without them, because a PIN with a default is a PIN
written into this repository. While you are in there, say who the Diary is actually about —
that part is worth doing before the first start, since the Child on record is not overwritten
afterwards. Everything else falls back to a working default.

```sh
cp .env.example .env    # then fill in PIN and SESSION_SECRET
docker compose up --build
```

That starts four containers: Postgres, the API — which migrates, seeds and then serves both the
JSON and the built frontend — and the scheduler, which sends the evening notification and nothing
else (ADR-0009), and the nightly dump (ADR-0008).

Then open <http://localhost:8000>, type the PIN, say which Parent you are, and the first Prompt
is on the screen. `docker compose down` stops everything; add `-v` to discard the database
volume as well.

## Signing in

The app is published only to the family tailnet (ADR-0005), so authentication inside it is a
second lock rather than the first: one shared PIN, so that a phone somebody picks up does not
open onto the Diary. Typing it exchanges it for a cookie signed with `SESSION_SECRET` and good
for a year, and every endpoint but that exchange refuses a request without one.

The PIN is shared, so it says only that this phone has it. Which of the two Parents is holding
it is a second question, answered by picking one of the two seeded names; the same cookie is
re-issued carrying the choice (ADR-0010). It is a claim rather than a credential — both Parents
read everything either of them writes anyway. The cookie carries its own proof, so nothing is
stored server-side: a restarted API still knows both phones and whose they are, and changing
`SESSION_SECRET` signs every device out.

## Answering, and skipping

A Sitting is one stretch of answering: one Prompt, a box, and submitting draws the next one —
never a form of several questions (ADR-0004). A Prompt that is not for tonight is skipped
instead, which draws the next one just the same. The two Parents are drawn from independently,
so what one of them answered tonight says nothing about what the other is shown.

The draw is ADR-0004's rule in full — one filter, then three orderings:

1. A Prompt this Parent has already answered this **Diary day** is out.
2. Of what is left, one not yet seen tonight comes before one skipped tonight — so a Skip is
   re-offered only once nothing unseen remains.
3. Within that, the one this Parent answered longest ago comes first. Never answered is the
   longest ago there is.
4. Where the rules still prefer nothing, `Chance` picks (`backend/app/chance.py`). It is
   injected like the clock, so the suite seeds it and a failing draw fails again next run.

Skips are stored one row per Parent, Prompt and Diary day, and kept rather than forgotten: it
is what lets a Skip come back later the same evening, and the only way to learn later which
Prompts get reliably dodged. Because that record is the point, a Prompt is never both answered
and skipped on one Diary day — skipping one already answered today is refused with a 409, and
the phone quietly draws again.

A Diary day runs 04:00 to 04:00 in `TIMEZONE` rather than midnight to midnight, because parents
of small children are awake at hours that do not respect calendars: an Answer written at 01:30
belongs to the evening that just ended, and at 04:00 the bank fills up again. The clock behind
it is injected (`backend/app/clock.py`) with exactly one production implementation, so the tests
can place themselves at 01:30 instead of waiting for it.

## Reading the Diary

There is one Diary, not one per Parent (ADR-0001), so `GET /api/diary` takes no account of who
is asking and both Parents get the same bytes. It comes back as Diary days rather than as a run
of Answers: the date and the Child's age belong to the evening rather than to each sentence
written in it, and both Parents' Answers sit under the same heading — which is what makes the
Diary read as shared rather than as two accounts side by side.

Newest evening first, and newest Answer first within an evening. The age on each evening is
derived from the birthdate rather than stored (ADR-0002): it is the age the Child *was*, so an
evening from four years ago still says so.

## The schema and the seed

The API migrates and seeds itself on every start, before it serves anything, so a rebuilt Pi
comes up with a usable Prompt bank and a restart costs nothing.

- **Migrations** are Alembic, in `backend/migrations/`. The schema is created there and
  nowhere else; the application never creates a table for itself.
- **The seed** (`backend/app/seed.py`) is idempotent, and it only ever adds. The Child and
  the two Parents are taken from configuration on the first start; after that the database
  is the record, and configuration that disagrees with it is logged and ignored rather than
  applied — a stack restarted without its `.env` must never overwrite a captured birthdate
  with a placeholder.

The Prompt bank is seeded, never edited from inside the app (ADR-0004): change the prompts in
[`docs/prompt-bank.md`](docs/prompt-bank.md) and in `PROMPT_BANK`, then restart. Migrations are
written by hand, which makes `backend/app/models.py` a second statement of the same schema, so
check the two still agree with `docker compose run --rm tests alembic check`.

## Going further

The three parts of this project with the most operational surface have documents of their own:

- [**Installing it on a phone**](docs/push-notifications.md) — the PWA, the one permission
  prompt iOS gives you, how an evening's notification is drawn, recorded and sent, what happens
  when it is tapped, and the VAPID subject that Apple turned out to verify.
- [**Backing it up**](docs/backups.md) — the nightly dump, the check that restores it and holds
  the text against the Diary word for word, and how to actually restore one.
- [**Deploying to the Pi**](docs/deploying-to-the-pi.md) — the machine, Docker, Tailscale Serve,
  Syncthing, and `deploy/check.sh`, which asks the Pi whether the deployment is what these
  documents say it is.

## Running the tests

```sh
docker compose run --rm --build tests
```

Tests drive the API over HTTP through FastAPI's test client, against a **real Postgres** — not
SQLite and not a fake repository, because the draw queries this project is really about are
exactly the kind of SQL that differs between engines. They assert what a Parent can observe,
never how the modules behind the endpoint are arranged. The `client` fixture is signed in
through the real PIN exchange rather than by planting a cookie, because that is the state a
Parent is in for all but the first few seconds they ever spend in the app.

The suite works in a `kidiary_test` database on the same Postgres server, so it never disturbs
the data behind `docker compose up`, and each run rebuilds it with the same migrations and seed
the API boots through.

## Working on the frontend

The Vite dev server gives hot reloading and proxies `/api` to the container, so run the stack
as above and then:

```sh
cd frontend
npm install
npm run dev
```

That serves the frontend on <http://localhost:5173> against the API on port 8000. Use
`npm run build` for a typecheck plus production build, and `npm run lint` for oxlint.

## Layout

| Path                 | Holds                                                                                                  |
| -------------------- | ------------------------------------------------------------------------------------------------------ |
| `backend/app/`       | The FastAPI application                                                                                  |
| `backend/migrations/`| Alembic migrations. The schema lives here                                                                |
| `backend/tests/`     | pytest, driving the API over HTTP against a real Postgres                                                |
| `frontend/`          | The React + Vite + TypeScript frontend, and the PWA manifest, icons and service worker (ADR-0006)        |
| `Dockerfile`         | Multi-stage: the frontend is built with Node, then copied into the Python image, so Node never reaches the Pi (ADR-0007) |
| `backup/`            | The nightly dump, and the two checks that hold it to its word (ADR-0008)                                 |
| `docker-compose.yml` | Postgres, the API image that serves the built frontend, the scheduler running that same image (ADR-0009), and the dump running in Postgres's own (ADR-0008) |
| `docker-compose.pi.yml` | The whole of what the Pi does differently: the API on loopback, and the cookie `Secure` (ADR-0005) |
| `deploy/`            | `check.sh`, which asks the Pi whether the deployment is what it should be |
| `docs/adr/`          | The ten decisions, each with its context and its consequences |
