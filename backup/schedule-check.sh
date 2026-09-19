#!/bin/sh
#
# Hold the nightly schedule to a table of moments (ADR-0008).
#
#   docker compose run --rm backup sh -c 'sh /opt/kidiary/schedule-check.sh'
#
# The dump job has exactly one piece of reasoning in it — which Diary day a dump taken
# now is of — and everything else follows from it: what the file is called, and whether
# tonight's dump has been taken. So it is asked here about a fixed set of evenings rather
# than only about the one the container happens to be running on, the same way the suite
# places the API at 01:30 instead of waiting for it.
#
# Three of the rows below are the reason this file exists. An hour that goes missing and
# an hour that happens twice are the two nights a nightly job is most likely to skip or
# double, and they are a calendar away from where anyone would notice.

set -eu

#: The rule is asked about German evenings, whatever zone the container was started in:
#: these expectations are about two particular nights in 2026, not about the family's
#: timezone, and the last Sunday in March is only interesting in a zone that observes it.
TZ=Europe/Berlin
export TZ

NIGHTLY="$(dirname "$0")/nightly.sh"

failures=0

expect() {
    moment=$1
    wanted=$2
    because=$3

    at=$(date -d "$moment" +%s)
    got=$(sh "$NIGHTLY" --settled-day "$at")

    if [ "$got" = "$wanted" ]; then
        printf '  ok    %s -> %s   %s\n' "$moment" "$got" "$because"
    else
        printf '  FAIL  %s -> %s, wanted %s   %s\n' "$moment" "$got" "$wanted" "$because"
        failures=$(( failures + 1 ))
    fi
}

echo 'The Diary day a dump taken at each moment is of:'
echo

expect '2026-09-12 04:14:00' '2026-09-10' 'a minute early: last night is not settled yet'
expect '2026-09-12 04:15:00' '2026-09-11' 'the Diary day that closed at four this morning'
expect '2026-09-12 12:00:00' '2026-09-11' 'still, at midday: its dump was taken at 04:15'
expect '2026-09-12 23:59:00' '2026-09-11' 'still, at midnight: tonight is not over'
expect '2026-09-13 03:00:00' '2026-09-11' 'still, at three: an Answer can arrive until four'
expect '2026-09-13 04:15:00' '2026-09-12' 'and now the next one'

echo
echo 'The night the clocks go back, when 02:00 to 03:00 happens twice:'
echo
expect '2026-10-25 01:30:00' '2026-10-23' 'the small hours, before the hour is repeated'
expect '2026-10-25 02:30:00' '2026-10-23' 'inside the repeated hour itself'
expect '2026-10-25 03:15:00' '2026-10-23' 'four and a quarter hours have elapsed; the clock says 03:15'
expect '2026-10-25 03:59:00' '2026-10-23' 'a minute before the Diary day closes, whatever has elapsed'
expect '2026-10-25 04:15:00' '2026-10-24' 'and now it has closed'
expect '2026-10-26 04:15:00' '2026-10-25' 'the night after it is ordinary again'

echo
echo 'The night the clocks go forward, when 02:00 to 03:00 never happens:'
echo
expect '2026-03-29 01:30:00' '2026-03-27' 'the small hours, before the hour goes missing'
expect '2026-03-29 04:15:00' '2026-03-28' 'the clock reads 04:15, so the day has closed'
expect '2026-03-30 04:15:00' '2026-03-29' 'the night after it is ordinary again'

echo
echo 'Across the turn of the year:'
echo
expect '2027-01-01 04:15:00' '2026-12-31' "new year's morning dumps the old year's last evening"

echo
if [ "$failures" -ne 0 ]; then
    echo "$failures of the moments above are wrong." >&2
    exit 1
fi

echo 'Every moment lands on the Diary day it should.'
