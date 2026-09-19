#!/bin/sh
#
# Restore a dump into a throwaway database and prove it holds the Diary (ADR-0008).
#
#   docker compose run --rm backup sh -c 'sh /opt/kidiary/restore-check.sh [dump]'
#
# An untested backup is a hypothesis, and the way it usually fails is silent: the file is
# there every morning, the right size, and nothing reads it until the evening it is the
# only copy left. So this restores a real dump into a database of its own, holds what came
# back against the Diary, and drops it again. It never writes to the Diary itself.
#
# What it can and cannot conclude is worth being exact about, because the Diary has moved
# on since the dump was taken — that is what a nightly dump *is*. Answers are written and
# never unwritten; a Device the push service reports `410 Gone` is deleted. So counts that
# differ are not news, and a check that failed on them would go red every morning and be
# ignored by the second week.
#
# What it refuses to accept:
#
#   * a restore that errors anywhere (`ON_ERROR_STOP`), or a table that did not come back;
#   * a dump that restores cleanly and holds no schema at all, which is what a database
#     the API has not migrated yet dumps to — the worthless backup that looks entirely well;
#   * Answers that came back as different text than the Diary holds for them — compared as
#     a digest over the range the dump covers, so later evenings do not enter into it;
#   * a dump with no Answers in it at all, while the Diary has some.
#
# The Answers are the point of the comparison: the text of what the two of them wrote is
# the one thing in this database that cannot be seeded, migrated, or typed in again.

set -eu
set -o pipefail

#: Postgres announces a `drop database if exists` that had nothing to drop, which is
#: the ordinary first run and not news.
PGOPTIONS="-c client_min_messages=warning"
export PGOPTIONS

DUMPS=${DUMPS:-/dumps}
THROWAWAY=${THROWAWAY:-kidiary_restore_check}
DIARY=${PGDATABASE:?the database the Diary lives in must be named in PGDATABASE}

#: Everything the schema holds. The three the ticket asks after are here, and so is the
#: rest: a restore that brought back the Answers but not the Deliveries would be a
#: restore that passes a narrower check and still costs a Parent their evening.
TABLES='children parents prompts answers skips deliveries push_subscriptions'

if [ "$THROWAWAY" = "$DIARY" ]; then
    echo "Refusing to restore over $DIARY itself." >&2
    exit 2
fi

# A dump is named by its path inside this container, which is /dumps. The `|| true` is
# load-bearing: with `set -e` and `pipefail`, a glob that matches nothing makes `ls` fail
# and would end the script here, before the message below could explain why.
dump=${1:-$(ls -1 "$DUMPS"/kidiary-*.sql.gz 2>/dev/null | sort -r | head -n 1 || true)}
if [ -z "$dump" ]; then
    echo "There is no dump in $DUMPS to restore." >&2
    exit 2
fi
if [ ! -f "$dump" ]; then
    echo "$dump is not a file. A dump is named by its path inside this container," >&2
    echo "which is /dumps/..., not ./backups/... on the host." >&2
    exit 2
fi

ask() {
    psql -q -tAd "$1" -c "$2"
}

count() {
    ask "$1" "select count(*) from $2"
}

#: The Answers themselves, ordered and hashed, so that identical counts of different text
#: cannot pass for a restore. Up to a given id, so that the Diary's later evenings — which
#: no dump from this morning could contain — are not held against it.
answers_digest() {
    ask "$1" "select coalesce(md5(string_agg(text, '|' order by id)), 'no answers')
              from answers where id <= $2"
}

echo "Restoring $(basename "$dump") into $THROWAWAY."

psql -q -d postgres -c "drop database if exists $THROWAWAY"
psql -q -d postgres -c "create database $THROWAWAY"

# ON_ERROR_STOP, because psql's default is to shrug at a failed statement and carry on to
# the end — which would restore three tables out of seven and exit 0.
if ! gunzip -c "$dump" | psql -q -v ON_ERROR_STOP=1 -d "$THROWAWAY" > /dev/null; then
    echo "The restore itself failed. $THROWAWAY is left in place to look at." >&2
    exit 1
fi

# A dump that restores cleanly and brings back no schema at all is not a strange edge: it
# is what `pg_dump` produces from a database the API has not migrated yet, and it is the
# one worthless backup that looks entirely well from the outside — a real file, a plausible
# name, a few hundred bytes. Caught here rather than in the loop below, where it surfaces
# as a bare `relation "children" does not exist` that reads like a bug in this script.
# Asked so that psql failing and psql answering NULL are told apart: the second means a
# dump with no schema, and the first means the database could not be reached — and
# advising somebody to delete a perfectly good dump because the server blinked would be
# the worst possible thing for this file to say.
if ! schema=$(ask "$THROWAWAY" "select to_regclass('public.answers')"); then
    echo "The restored database could not be asked what it holds." >&2
    echo "$THROWAWAY is left in place to look at." >&2
    exit 2
fi
if [ -z "$schema" ]; then
    echo "$(basename "$dump") restored without error and holds no tables at all." >&2
    echo "That is a dump of a database that had no schema when it was taken — almost" >&2
    echo "certainly the first dump on a new stack, taken before the API had migrated." >&2
    echo "Delete it and the job takes that Diary day again within the minute." >&2
    exit 1
fi

printf '\n%-20s %10s %10s\n' 'table' "$DIARY" 'restored'
printf '%-20s %10s %10s\n' '--------------------' '----------' '----------'

for table in $TABLES; do
    # A table that did not come back fails here, through `set -e`: psql exits non-zero on
    # a relation that does not exist, and this assignment carries that out of the loop.
    here=$(count "$DIARY" "$table")
    there=$(count "$THROWAWAY" "$table")

    printf '%-20s %10s %10s' "$table" "$here" "$there"
    if [ "$here" -gt "$there" ]; then
        printf '   +%s since the dump' "$(( here - there ))"
    elif [ "$there" -gt "$here" ]; then
        printf '   %s no longer in the Diary' "$(( there - here ))"
    fi
    printf '\n'
done

restored_answers=$(count "$THROWAWAY" answers)
diary_answers=$(count "$DIARY" answers)
up_to=$(ask "$THROWAWAY" 'select coalesce(max(id), 0) from answers')

printf '\n'

if [ "$restored_answers" -eq 0 ] && [ "$diary_answers" -gt 0 ]; then
    echo "The dump holds no Answers at all, and the Diary holds $diary_answers." >&2
    echo "$THROWAWAY is left in place to look at." >&2
    exit 1
fi

here=$(answers_digest "$DIARY" "$up_to")
there=$(answers_digest "$THROWAWAY" "$up_to")

if [ "$here" != "$there" ]; then
    echo "The $restored_answers restored Answers are not the text the Diary holds for them:" >&2
    echo "  the Diary: $here" >&2
    echo "  restored:  $there" >&2
    echo "Either this dump is not a backup, or an Answer has been edited or deleted in the" >&2
    echo "database since it was taken — which is a thing somebody does on purpose." >&2
    echo "$THROWAWAY is left in place to look at." >&2
    exit 1
fi

psql -q -d postgres -c "drop database $THROWAWAY"

echo "The $restored_answers Answers in the dump are the Diary's own text, word for word:"
echo "  $here"
echo
echo "Restored $(basename "$dump") whole. $THROWAWAY has been dropped again."
