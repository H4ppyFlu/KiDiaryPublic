#!/bin/sh
#
# Hold the deployment to the ticket's word (#14, and ADR-0005 and ADR-0007 behind it).
#
#   sh deploy/check.sh
#
# Run on the Pi, from the checkout, on the host rather than in a container: most of what
# it asks about is true of the host and invisible from inside the stack — which interface
# a port is bound to, what Tailscale is publishing, what comes back after a reboot.
#
# It exists because "deployed" is the kind of claim that is easy to believe and hard to
# have checked. The stack being up says nothing about whether the app is also answering
# the home wifi in the clear, and the app answering says nothing about whether it will
# still be there after the next power cut. Each of those is one command; nobody runs ten
# commands twice, so here they are as one.
#
# **What it cannot conclude** is listed at the end and printed every run, because half of
# what #14 asks for happens on two phones and cannot be seen from here. A green run is
# the machine half of the ticket, not the ticket.

set -eu

#: Where the Diary is, so the script can be run from anywhere.
cd "$(dirname "$0")/.."

passed=0
failed=0
skipped=0

ok() {
    passed=$(( passed + 1 ))
    printf '  ok       %s\n' "$*"
}

#: A failure is reported and the run continues. Stopping at the first one would mean
#: learning about the Pi's problems one power cycle at a time.
no() {
    failed=$(( failed + 1 ))
    printf '  FAIL     %s\n' "$*"
}

#: Something this script is not in a position to answer — a missing tool, usually. Named
#: apart from a pass so that a green run with four skips cannot read as a green run.
skip() {
    skipped=$(( skipped + 1 ))
    printf '  skipped  %s\n' "$*"
}

note() {
    printf '           %s\n' "$*"
}

heading() {
    printf '\n%s\n' "$*"
}


heading 'The machine (ADR-0007)'

arch=$(uname -m)
case "$arch" in
    aarch64|arm64)
        ok "64-bit ARM: $arch."
        ;;
    armv7l|armv6l)
        no "$arch — this is 32-bit Raspberry Pi OS, and ADR-0007 says arm64."
        note 'The images would have to be the 32-bit ones, and Postgres 17 publishes'
        note 'none. Reflash with the 64-bit image rather than working around it.'
        ;;
    *)
        skip "$arch is not an ARM machine; this script is written for the Pi."
        ;;
esac

# Compose v2.24 is where `!override` arrived, which docker-compose.pi.yml turns on to
# replace the published port rather than adding a second one beside it. An older Compose
# reads the tag as an unknown one and errors, so this is a clearer message than the one
# that would otherwise arrive at `up` time.
if compose_version=$(docker compose version --short 2>/dev/null); then
    # Some 2.x releases print `v2.20.2` and some `2.20.2`. Without stripping the `v`, the
    # patterns below match nothing and precisely the old versions this is here to catch
    # would be waved through.
    case "$compose_version" in
        1.*|v1.*|2.[0-9].*|v2.[0-9].*|2.1[0-9].*|v2.1[0-9].*|2.2[0-3].*|v2.2[0-3].*)
            no "Compose $compose_version is older than 2.24 and cannot read \`!override\`."
            note "Raspberry Pi OS's \`docker.io\` package is the usual reason. See docs/deploying-to-the-pi.md."
            ;;
        *)
            # Inside the `case` rather than above it, so that a version which then fails
            # does not also count as a pass for the same fact.
            ok "Docker Compose $compose_version."
            ;;
    esac
else
    no 'No `docker compose`. The `docker.io` apt package ships none; see docs/deploying-to-the-pi.md.'
fi


heading 'The stack'

# --format is asked for explicitly: `docker compose ps` renders a table whose columns
# have moved between versions, and this reads one of them.
# `--all`, because without it a service that crashed or exited is simply absent, and this
# script would call it "not there at all" — in the one place whose whole job is saying
# what is wrong. With it, the state Docker recorded is what gets reported.
if running=$(docker compose ps --all --format '{{.Service}} {{.State}}' 2>/dev/null); then
    for service in db api scheduler backup; do
        state=$(printf '%s\n' "$running" | awk -v s="$service" '$1 == s { print $2 }')
        case "$state" in
            running) ok "$service is running." ;;
            '')      no "$service is not there at all." ;;
            *)       no "$service is $state." ;;
        esac
    done
else
    no 'The stack is not up, or this is not the directory it was brought up from.'
fi


heading 'The only way in is Tailscale Serve (ADR-0005)'

# The published binding as Docker actually made it, rather than as the YAML asked for it.
# These differ exactly when docker-compose.pi.yml was not passed — which is the mistake
# this section is here to catch, and which is invisible from the app.
if published=$(docker compose port api 8000 2>/dev/null) && [ -n "$published" ]; then
    case "$published" in
        127.0.0.1:*)
            ok "The API is published on $published — loopback only."
            ;;
        0.0.0.0:*|'[::]:'*)
            no "The API is published on $published — every interface, including the home wifi."
            note 'docker-compose.pi.yml was not passed, or was passed without `!override`.'
            note 'Check with: docker compose config | grep -A4 "ports:"'
            ;;
        *)
            no "The API is published on $published, which is neither loopback nor everything."
            ;;
    esac
else
    skip 'The API is not publishing a port; nothing to say about which interface.'
fi

# The host's own answer, which is the one that decides whether a packet from the wifi is
# accepted. Docker writes its forwarding rules below the addresses `ss` reports, so this
# is a second witness rather than the same one twice.
if command -v ss >/dev/null 2>&1; then
    listening=$(ss -Hltn 'sport = :8000' 2>/dev/null || true)
    if [ -z "$listening" ]; then
        skip 'Nothing is listening on 8000 for `ss` to describe.'
    elif printf '%s\n' "$listening" | grep -qE '(0\.0\.0\.0|\*|\[::\]):8000'; then
        no 'Something is listening on 8000 on every interface:'
        printf '%s\n' "$listening" | sed 's/^/           /'
    else
        ok 'Nothing on 8000 is listening on a wildcard address.'
    fi
else
    skip '`ss` is not installed (iproute2); the host side of the bind is unchecked.'
fi

# And the same question asked from outside, over the wire, which is the only form of it a
# guest's phone would ever ask. A refused connection is the pass.
lan=$(ip -4 -o addr show scope global 2>/dev/null |
      grep -v ' tailscale[0-9]* ' | awk '{ print $4 }' | cut -d/ -f1 | head -n 1)
if [ -n "$lan" ]; then
    if curl -sS -o /dev/null -m 4 "http://$lan:8000/" 2>/dev/null; then
        no "http://$lan:8000/ answered. The Diary is on the home wifi in the clear."
    else
        ok "http://$lan:8000/ does not answer, from the Pi's own LAN address."
    fi
else
    skip 'No non-Tailscale address found to try the LAN from.'
fi


heading 'Published on the tailnet'

serve_url=''
if ! command -v tailscale >/dev/null 2>&1; then
    no 'Tailscale is not installed on this machine.'
else
    serve_status=$(tailscale serve status 2>/dev/null || true)
    serve_url=$(printf '%s\n' "$serve_status" |
                grep -oE 'https://[a-zA-Z0-9.-]+\.ts\.net' | head -n 1)

    if [ -z "$serve_url" ]; then
        no 'Tailscale Serve is not publishing anything.'
        note 'Start it with: tailscale serve --bg 8000'
    else
        ok "Serve is publishing $serve_url."

        if printf '%s\n' "$serve_status" | grep -q '127.0.0.1:8000'; then
            ok 'and it forwards to 127.0.0.1:8000, which is where the API is.'
        else
            no 'but not to 127.0.0.1:8000. It is publishing something else.'
            printf '%s\n' "$serve_status" | sed 's/^/           /'
        fi

        # Funnel is the one setting that would undo the whole decision, so it is asked
        # after rather than assumed from Serve having been the command that was typed.
        #
        # Asked as the positive `(tailnet only)` rather than by looking for the word
        # Funnel: `tailscale funnel status` prints the *Serve* configuration, URL and all,
        # whether or not Funnel is on, so anything hunting for "https://" there reports
        # Funnel on every correctly configured machine. `(tailnet only)` is the phrase
        # Tailscale puts on that line precisely when the node is not publicly published.
        if printf '%s\n' "$serve_status" | grep -qF '(tailnet only)'; then
            ok 'Tailnet only: the Diary is not on the public internet.'
        elif tailscale serve status --json 2>/dev/null |
             tr -d ' \n' | grep -q '"AllowFunnel":{[^}]*:true'; then
            no 'Funnel is on. ADR-0005 says never Funnel: that is the public internet.'
            note 'Turn it off with: tailscale funnel --bg off'
        else
            no 'Serve does not say "(tailnet only)", and this cannot confirm it is private.'
            printf '%s\n' "$serve_status" | sed 's/^/           /'
        fi
    fi
fi

if [ -n "$serve_url" ]; then
    # A 200 from the root is the app shell arriving over a browser-trusted certificate —
    # curl verifies it without being told to, which is the whole reason Serve was chosen.
    # `|| code='000'` on the assignment, not `|| echo` inside it: curl prints the code
    # it got before it exits, so an `echo` in the substitution appends to that rather than
    # replacing it, and a failed request reads as the impossible status 200000.
    code=$(curl -sS -o /dev/null -w '%{http_code}' -m 15 "$serve_url/" 2>/dev/null) || code='000'
    case "$code" in
        200) ok "GET $serve_url/ -> 200, certificate and all." ;;
        000) no "GET $serve_url/ did not complete. Certificate, or Serve, or the API." ;;
        *)   no "GET $serve_url/ -> $code." ;;
    esac

    # 401 rather than 200: /api/health is behind the PIN, and this request carries no
    # cookie. That makes 401 the proof that the API itself — not a cached static file —
    # is on the other end, and that the guard in main.py is the thing answering.
    code=$(curl -sS -o /dev/null -w '%{http_code}' -m 15 "$serve_url/api/health" 2>/dev/null) || code='000'
    case "$code" in
        401) ok 'GET /api/health -> 401: the API is live and behind the PIN.' ;;
        200) no 'GET /api/health -> 200 without a cookie. The PIN guard is not on.' ;;
        000) no 'GET /api/health did not complete.' ;;
        *)   no "GET /api/health -> $code, which is neither the guard nor the answer." ;;
    esac
fi


heading 'Backups (ADR-0008)'

backup_dir=./backups
if [ -f .env ]; then
    # \042 and \047 are the double and single quote. Spelled in octal so that this line
    # does not have to nest one kind of quote inside the other to name them.
    from_env=$(grep -E '^[[:space:]]*BACKUP_DIR=' .env | tail -n 1 | cut -d= -f2- |
               tr -d '\042\047' || true)
    [ -n "$from_env" ] && backup_dir=$from_env
fi

if [ ! -d "$backup_dir" ]; then
    no "BACKUP_DIR is $backup_dir, and there is no such directory."
else
    # Asked of the backup container rather than worked out here, so that the answer comes
    # from the same code and the same clock that decides what to dump. It also could not
    # be run on this host: `nightly.sh` sets `pipefail`, which Debian's /bin/sh (dash) has
    # never had, while the busybox `ash` inside the container does.
    if settled=$(docker compose exec -T backup sh /opt/kidiary/nightly.sh --settled-day 2>/dev/null) &&
       [ -n "$settled" ]; then
        if [ -f "$backup_dir/kidiary-$settled.sql.gz" ]; then
            ok "The dump for the last settled Diary day is there: kidiary-$settled.sql.gz."
        else
            no "No dump for $settled, the last Diary day that has closed."
            note 'The job takes it at 04:15, and takes a missed one as soon as it can.'
        fi
    else
        skip 'The backup container could not be asked which Diary day has settled.'
    fi

    kept=$(find "$backup_dir" -maxdepth 1 -name 'kidiary-*.sql.gz' | wc -l)
    if [ "$kept" -gt 0 ]; then
        ok "$kept dump(s) in $backup_dir."
    else
        no "$backup_dir holds no dumps at all."
    fi
fi


heading 'After the next power cut'

if command -v systemctl >/dev/null 2>&1; then
    for unit in docker tailscaled; do
        enabled=$(systemctl is-enabled "$unit" 2>/dev/null || true)
        case "$enabled" in
            enabled|enabled-runtime|static|alias|indirect)
                ok "$unit starts at boot ($enabled)."
                ;;
            '')
                no "$unit is not a unit systemd knows about."
                ;;
            *)
                no "$unit is $enabled — it will not start at boot."
                note "Fix with: sudo systemctl enable --now $unit"
                ;;
        esac
    done
else
    skip 'No systemd; whether docker and tailscaled start at boot is unchecked.'
fi

# `restart: unless-stopped` in the Compose file is the other half: systemd starts the
# daemon, and the policy is what makes the daemon start these four.
# `--all` again: a stopped container is the one most likely to have the wrong restart
# policy, and the one this check exists to find.
if ids=$(docker compose ps -q --all 2>/dev/null) && [ -n "$ids" ]; then
    wrong=$(docker inspect -f '{{.Name}} {{.HostConfig.RestartPolicy.Name}}' $ids 2>/dev/null |
            awk '$2 != "unless-stopped" && $2 != "always" { print $1 " is " $2 }' || true)
    if [ -z "$wrong" ]; then
        ok 'Every container restarts on its own.'
    else
        no 'Some containers would stay down after a reboot:'
        printf '%s\n' "$wrong" | sed 's/^/           /'
    fi
fi

# The node key is the quiet one. Six months after a headless Pi joins a tailnet its key
# expires, the machine drops off, and the Diary stops being reachable one morning with no
# cause that is visible from the Pi — a power cut that lasts until somebody
# re-authenticates by hand. Only the control plane knows, so this needs `jq` to read.
if command -v tailscale >/dev/null 2>&1 && command -v jq >/dev/null 2>&1; then
    # jq given empty input prints nothing and exits 0, so a `tailscale status` that failed
    # arrives here as an empty string rather than as an error — and would be reported as a
    # key that "expires at ", which is worse than not checking.
    expiry=$(tailscale status --json 2>/dev/null | jq -r '.Self.KeyExpiry // "never"')
    if [ -z "$expiry" ]; then
        skip 'Tailscale could not be asked when this node'"'"'s key expires.'
    elif [ "$expiry" = 'never' ] || [ "$expiry" = 'null' ]; then
        ok "This node's key does not expire."
    else
        no "This node's key expires at $expiry, and the Pi drops off the tailnet then."
        note 'Disable key expiry for it in the admin console, under Machines.'
    fi
else
    skip 'Key expiry unchecked (needs jq). Confirm it is disabled in the admin console.'
fi


heading 'What this cannot tell you'

note 'Both phones on the tailnet, with the PWA on the home screen.'
note 'A notification actually arriving on each phone, and opening its own Prompt.'
note 'Syncthing holding the same dumps on the laptop.'
note 'A dump from this Pi restored, which is its own command:'
note '  docker compose run --rm backup sh -c "sh /opt/kidiary/restore-check.sh"'

printf '\n%s passed, %s failed, %s skipped.\n' "$passed" "$failed" "$skipped"

if [ "$failed" -ne 0 ]; then
    exit 1
fi
