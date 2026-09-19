#!/bin/sh
#
# The nightly dump of the whole Diary (ADR-0008).
#
# It runs in the database's own image rather than the API's, because a `pg_dump` older
# than the server it dumps refuses to run at all: taking the client out of the image the
# server runs from is the one version rule that cannot drift. Nothing is built for this
# service — the file you are reading is bind-mounted in, so deploying a change to the job
# is a `git pull`.
#
# **The dumps are not encrypted, and that is a decision rather than an omission.**
# ADR-0008: they never leave two personally-owned machines and travel between them over
# an encrypted tailnet, so a passphrase would be one more thing to lose. That ADR carries
# its own condition for changing it, and this is the file that would change:
#
#   > If a cloud destination is ever added, encryption becomes required.
#
# Syncing this directory off the machine belongs to the deployment (#14); this only fills
# it, and `restore-check.sh` beside it is what says the filling worked.
#
# Like the evening scheduler (ADR-0009) it is a loop that wakes once a minute and asks a
# cheap question rather than a cron entry, because of what the question is: "is the dump
# for the last settled Diary day on disk?" is answered by the directory itself. So a
# container restarted at a quarter past four cannot take a second dump, and one that was
# off for a day takes the missed one the moment it comes back.

set -eu
set -o pipefail

#: Where the dumps land. The host directory behind it is what Syncthing mirrors.
DUMPS=${DUMPS:-/dumps}

#: How many nightly dumps to keep. These are kilobytes, so a longer memory costs nothing;
#: seven is a week of evenings, which is longer than it takes to notice a mistake.
KEEP=${KEEP:-7}

#: How often to ask. Almost every pass is one `test -f`.
TICK=${TICK:-60}

#: When the dump is taken, on the clock. A Diary day runs 04:00 to 04:00, so a quarter of
#: an hour past four the day that just closed is complete and nothing will ever be written
#: into it again. It is not configurable, because it is not a preference: it is
#: `diary_day.py`'s boundary plus enough slack to be sure of it.
#:
#: **On the clock** is the whole of it, and the reason this is a string. `diary_day.py`
#: decides which Diary day an Answer belongs to by comparing the wall clock to 04:00, so a
#: dump that asks its question any other way is asking a different question than the app
#: answers. Elapsed seconds since local midnight reads like the same thing and is not: on
#: the night the clocks go back, four and a quarter hours of it have passed by 03:15 on the
#: clock, so the dump would be taken three quarters of an hour before the day it is named
#: after had closed — and because the file then exists, it would never be retaken.
SETTLES_AT='0415'

#: `INFO backup:` rather than a timestamp, so these lines sit beside the API's and the
#: scheduler's in one `docker compose logs`. Docker keeps the time.
log() {
    printf 'INFO backup: %s\n' "$*"
}

warn() {
    printf 'WARNING backup: %s\n' "$*" >&2
}

#: The last Diary day that has closed and settled: the day a dump taken now would be of,
#: and the name it would be filed under. This is the whole schedule — the loop takes a
#: dump whenever this names a day that has none.
#:
#: Takes a moment, so that `schedule-check.sh` can ask it about a night in October.
the_settled_day() {
    at=${1:-}
    [ -n "$at" ] || at=$(date +%s)

    today=$(date -d "@$at" +%F)
    # Zero-padded and four characters wide, which is what makes comparing it as a string
    # a comparison of times. A string also keeps arithmetic out of it, which matters more
    # than it looks: in `ash`, a leading zero inside $(( )) is octal, so an hour of 08 or
    # 09 is a syntax error rather than a wrong answer.
    o_clock=$(date -d "@$at" +%H%M)

    if [ "$o_clock" '<' "$SETTLES_AT" ]; then
        # Before this morning's dump: the day that has settled is the one before
        # yesterday's, and yesterday's own dump was taken at 04:15 this morning.
        days_back=2
    else
        days_back=1
    fi

    # Counted back from noon rather than from now, because noon is the one anchor that an
    # hour of daylight saving in either direction cannot move across midnight. A date is
    # a calendar fact, and 86400 seconds is not always a day.
    noon=$(( $(date -d "$today 00:00:00" +%s) + 12 * 3600 ))
    date -d "@$(( noon - days_back * 86400 ))" +%F
}

#: Is the Diary's schema there yet?
#:
#: This job and the API come up together — both wait only for Postgres to be healthy — and
#: the API migrates *after* it has started. On a database that has never been migrated,
#: which is a new Pi or a restore onto blank hardware, that is a race this loop loses: the
#: last settled Diary day has no dump, so it takes one, and `pg_dump` of a database with no
#: tables succeeds and writes several hundred bytes of nothing.
#:
#: What makes that unrecoverable rather than merely wrong is the schedule. The only question
#: this loop asks is "is the dump for this day on disk?", and a file full of nothing answers
#: yes for good — so the day it is named after is never dumped again, the first real backup
#: is silently tomorrow's, and the directory looks right the whole time. That is the precise
#: shape of failure ADR-0008 exists to refuse.
#:
#: So: the rule the scheduler already lives by. A pass that finds the schema not there yet
#: is logged and retried a minute later.
#: Three answers rather than two, because "the Diary has no schema yet" and "the database
#: could not be asked" are different problems and only one of them goes away on its own.
#: Collapsing them would report a database that is down, restarting, or refusing the
#: password as an empty schema — and then wait quietly for a migration that is not coming.
#:
#:   0  the schema is there
#:   1  the database answered, and there is none yet
#:   2  the database could not be asked at all
the_schema_is_there() {
    answer=$(psql -tAc "select to_regclass('public.answers')" 2>/dev/null) || return 2
    [ -n "$answer" ]
}


#: Dump one Diary day, or say it failed. Nothing partial is ever left under a real name.
dump() {
    day=$1
    final="$DUMPS/kidiary-$day.sql.gz"
    partial="$DUMPS/.kidiary-$day.sql.gz.partial"

    # Written under a dotted, partial name and moved into place only once both `pg_dump`
    # and `gzip` have succeeded. Two readers depend on that: the loop below takes the
    # presence of a dump as "this day is done", and Syncthing mirrors whatever it finds.
    # Neither may ever see half a dump. `pipefail` is what makes this true only when the
    # dump *and* the compression worked — without it a `pg_dump` that died halfway would
    # still gzip cleanly, which is exactly the backup that looks right every morning
    # until the one it is needed.
    if ! pg_dump --no-owner --no-privileges | gzip > "$partial"; then
        rm -f "$partial"
        return 1
    fi

    mv "$partial" "$final"
    log "The Diary day $day is dumped: $(basename "$final"), $(wc -c < "$final") bytes."
}

#: Keep the newest $KEEP dumps and remove the rest. The names are ISO dates, so sorting
#: them by name sorts them by evening.
prune() {
    ls -1 "$DUMPS"/kidiary-*.sql.gz 2>/dev/null | sort -r | tail -n +$(( KEEP + 1 )) |
        while IFS= read -r old; do
            rm -f "$old"
            log "Removed $(basename "$old"); the last $KEEP dumps are kept."
        done
}

#: Clear out any half-written dump left by a process that was killed mid-`pg_dump` — the
#: power cut this whole job exists in case of. `prune` cannot reach them: they are named
#: so that nothing mistakes them for a backup, which also means the retention glob does
#: not match them, and they would otherwise collect one per crash in the directory
#: somebody goes looking at on the worst morning.
clear_partials() {
    for leftover in "$DUMPS"/.kidiary-*.sql.gz.partial; do
        [ -e "$leftover" ] || continue
        rm -f "$leftover"
        log "Cleared $(basename "$leftover"), left behind by a dump that was interrupted."
    done
}

# `nightly.sh --settled-day [epoch]` answers the question the schedule turns on and
# stops, which is the seam `schedule-check.sh` holds to a table of moments.
if [ "${1:-}" = '--settled-day' ]; then
    the_settled_day "${2:-}"
    exit 0
fi

stop() {
    log 'Stopped.'
    exit 0
}

trap stop TERM INT

log "Watching for the end of each Diary day, every ${TICK}s. Keeping $KEEP dumps in $DUMPS."
clear_partials

#: Whether the wait for the schema has already been mentioned. Once per wait rather than
#: once a minute: it is ordinary for the first seconds of a new stack, and only worth
#: reading if it does not stop.
waiting_for_schema=0

while :; do
    day=$(the_settled_day)

    if [ ! -f "$DUMPS/kidiary-$day.sql.gz" ]; then
        # `|| schema=$?` rather than a bare call, so that a non-zero answer is a value to
        # read rather than the end of the script under `set -e`.
        schema=0
        the_schema_is_there || schema=$?

        case "$schema" in
            0)
                # Cleared here rather than after a successful dump: the wait is over when
                # the schema arrives, and a dump that then fails has its own warning every
                # tick. Clearing it only on success would let one failure silence both.
                waiting_for_schema=0
                if dump "$day"; then
                    prune
                else
                    warn "The dump for $day failed; trying again next tick."
                fi
                ;;
            1)
                # Once per wait rather than once a minute: ordinary for the first seconds
                # of a new stack, and only worth reading if it does not stop.
                if [ "$waiting_for_schema" -eq 0 ]; then
                    waiting_for_schema=1
                    warn "The Diary has no schema yet. Waiting for the API to migrate before dumping $day, rather than writing an empty dump under its name."
                fi
                ;;
            *)
                # Every tick, deliberately. A database that cannot be reached is an outage
                # rather than a start-up moment, and the dumps are not being taken.
                warn "The database could not be asked whether the Diary is there; $day is not dumped. Trying again next tick."
                ;;
        esac
    fi

    # Slept in the background and waited for, so that Compose's SIGTERM is handled now
    # rather than after the tick runs out and the container is killed instead.
    sleep "$TICK" &
    wait $!
done
