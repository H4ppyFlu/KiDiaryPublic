# Backing it up

Part of [Kidiary](../README.md). The nightly dump (ADR-0008), the two checks that hold
it to its word, and how to actually restore one.

Every night at a quarter past four the whole database is dumped to a file on the host, and
the last seven dumps are kept. A quarter past four rather than midnight because a Diary day
runs 04:00 to 04:00: at 04:15 the evening that just ended is complete and nothing will be
written into it again, so the dump is named after it — `kidiary-2026-09-10.sql.gz` is the
Diary day of the tenth, whole.

The job is `backup/nightly.sh`, and it runs in Postgres's own image rather than the API's,
because a `pg_dump` older than the server it dumps refuses to run at all: taking the client
out of the image the server runs from is the one version rule that cannot drift. Nothing is
built for it — `backup/` is mounted in, so a `git pull` on the Pi deploys a change to the
job. Like the scheduler it wakes once a minute and asks a cheap question rather than being
a cron entry, and the question — is the dump for the last settled Diary day on disk? — is
answered by the directory itself. So a container restarted at 04:16 cannot take a second
dump, and one that was off all day takes the missed one the moment it comes back.

The job will not dump a database that has no schema yet. That sounds like a corner and is
the ordinary first minute of a new Pi: the dump service and the API both wait only for
Postgres to be healthy, and the API migrates after it starts, so the very first pass can
find a database with no tables in it. `pg_dump` is perfectly happy to dump one — a few
hundred bytes, a real filename, no tables — and because the schedule's only question is
whether a file for that Diary day exists, that file would answer yes for good and the day
would never be dumped again. So a pass that finds no schema is logged and retried a minute
later, exactly as the scheduler does, and `restore-check.sh` refuses such a dump by name if
one ever reaches it.

`BACKUP_DIR` says where the dumps land: on the Pi, the directory Syncthing mirrors to the
laptop (ADR-0008), and here a folder beside the repository. `BACKUP_KEEP` is how many are
kept; they are kilobytes, so a longer memory costs nothing. The hour is deliberately not
configurable, because it is not a preference — it is `diary_day.py`'s boundary plus enough
slack to be sure of it.

**The dumps are not encrypted**, per ADR-0008: they never leave two personally-owned
machines and travel between them over an encrypted tailnet, so a passphrase would be one
more thing to lose. That ADR's condition for changing it is written at the top of
`backup/nightly.sh`, which is the file that would have to change — *if a cloud destination
is ever added, encryption becomes required.*

## Proving a dump

An untested backup is a hypothesis, and the way it fails is silent: the file is there every
morning, the right size, and nothing reads it until the evening it is the only copy left.

```sh
docker compose run --rm backup sh -c 'sh /opt/kidiary/restore-check.sh'
```

It restores the newest dump into a throwaway database of its own, holds what came back
against the Diary, and drops it again. It never writes to the Diary:

```
table                   kidiary   restored
-------------------- ---------- ----------
children                      1          1
parents                       2          2
prompts                      20         20
answers                       5          2   +3 since the dump
skips                        12         10   +2 since the dump
deliveries                    1          1
push_subscriptions            1          1

The 2 Answers in the dump are the Diary's own text, word for word:
  97e2a613177fdaea9d3baba069f6e33e
```

Counts that differ are not a complaint. The Diary has moved on since the dump was taken —
that is what a nightly dump is — so evenings written since show up as `+3 since the dump`,
and a Device the push service reported `410 Gone` for shows up on the other side. A check
that went red on those would go red every morning and be ignored by the second week.

What it refuses to accept is a restore that errored anywhere, a table that did not come
back, a dump that restores cleanly and holds no schema at all, a dump with no Answers in it
while the Diary has some, and — the one that matters —
**Answers that came back as different text than the Diary holds for them**, compared as a
digest over the range the dump covers so that later evenings do not enter into it.
Identical counts of different words would otherwise pass for a restore. Any of those exits
non-zero and leaves the throwaway database in place to be looked at.

Pass a path to check an older dump, and note that it is the container's path rather than
the host's: `... 'sh /opt/kidiary/restore-check.sh /dumps/kidiary-2026-09-04.sql.gz'`. (The
`sh -c` wrapper is for Git Bash on Windows, which would otherwise rewrite `/opt/...` into a
Windows path before Docker ever sees it.)

The other half of the job is the schedule, which is the only reasoning in it: which Diary
day a dump taken now belongs to, and therefore whether tonight's has been taken at all.
That is asked about a fixed table of evenings rather than only about the one the container
happens to be running on —

```sh
docker compose run --rm backup sh -c 'sh /opt/kidiary/schedule-check.sh'
```

— including the night the clocks go back, when 02:00 to 03:00 happens twice, and the night
they go forward, when it never happens. Those are the two nights a nightly job is likeliest
to skip or to take twice, and they are a calendar away from where anyone would notice. The
rule is asked in wall-clock terms for the same reason `diary_day.py` is: four and a quarter
hours *elapsed* since midnight is 03:15 on the clock on the night the hour repeats, which
would take the dump before the day it is named after had closed.

## Actually restoring

Onto a machine that has never run the app, or over a database that has to go:

```sh
docker compose up -d db     # only the database: the API must not migrate or seed yet
docker compose exec -T db psql -U kidiary -d postgres \
    -c 'drop database if exists kidiary' -c 'create database kidiary'
gunzip -c backups/kidiary-2026-09-10.sql.gz |
    docker compose exec -T db psql -U kidiary -d kidiary -v ON_ERROR_STOP=1
docker compose up -d
```

Only `db` is up for a reason twice over: the API would migrate and seed an empty database
into something the dump then collides with, and a database cannot be dropped while the API
is holding a connection to it. The drop is there because the database already exists — the
Postgres entrypoint creates `POSTGRES_DB` the first time the volume is initialised, so
`create database kidiary` on a brand-new Pi fails with "already exists". Dropping first is
what makes these four lines the same four lines whether the volume is new or has been in
use for a year.

The dump carries the schema, the data and the Alembic version, so the API comes up on a
restored database and migrates from where the dump left off rather than from nothing. It
does not carry the role or the database itself, both of which Compose creates, and it does
not carry `.env` — the PIN, `SESSION_SECRET` and the VAPID pair are configuration, and a
Pi restored without them starts every phone over.
