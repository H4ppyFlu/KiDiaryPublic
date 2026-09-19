# Deploying to the Pi

Part of [Kidiary](../README.md). Taking the stack from a laptop to a Raspberry Pi that
runs it permanently, published to the tailnet and to nowhere else (ADR-0005).

The Pi runs the same four containers as the laptop. What differs is that its stack is
reachable and permanent, and `docker-compose.pi.yml` is the whole of the difference: it
binds the API to loopback and marks the sign-in cookie `Secure`. Between them those two
lines turn ADR-0005 from an intention into a fact — from outside the Pi the only route to
the Diary is Tailscale Serve, and there is no plain-http path left for a year-long cookie
to travel down.

`deploy/check.sh` is the other half of this document. Every step below ends up as something
it can ask about, so the way to know a deploy worked is to run it rather than to reread
this page.

## The machine

Kidiary wants 64-bit Raspberry Pi OS. Postgres 17 publishes no 32-bit ARM image at all, so
this is a prerequisite rather than a preference:

```sh
uname -m                    # aarch64. armv7l means reflash with the 64-bit image
```

Every deploy runs `npm ci` and a Vite build on the Pi (ADR-0007), and on a 2GB machine with
Postgres already resident that is the step that runs out of memory. Give it swap to fall back
on before the first build rather than after the first failure — and check what the swap it
already has actually is:

```sh
swapon --show
```

Recent Raspberry Pi OS comes with **zram** and nothing else, which shows up as `/dev/zram0` at
about the size of RAM. That is compressed swap held *in RAM*, so it buys some room but cannot
buy more than the machine has: under a build that wants more than 2GB in total it is competing
for the very memory it is standing in for. A disk-backed swapfile is the real backstop, and
there is no reason not to have both — zram keeps its high priority and is used first, the file
takes the overflow:

```sh
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab   # survives the reboot
swapon --show                                                # zram at 100, /swapfile below it
```

## Docker

Raspberry Pi OS packages Docker as `docker.io`, and that package will not do: its Engine is
old and it ships no `docker compose` at all — Compose there is the separate, retired Python
`docker-compose`, which does not understand the `!override` tag `docker-compose.pi.yml`
depends on. Replace it with Docker's own repository:

```sh
# One at a time, and tolerating a miss: `apt remove` given a package that is not on the
# machine aborts the whole command rather than skipping it, so naming six in one line
# removes none of them and leaves the old Docker in place — which `get.docker.com` then
# finds, warns about, and installs over.
for pkg in docker.io docker-doc docker-compose podman-docker containerd runc; do
    sudo apt-get remove -y "$pkg" || true
done
dpkg -l | grep -E 'docker|containerd' || echo 'nothing left to conflict'

curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
sudo systemctl enable --now docker
```

Then log out and back in, or the group change is not yours yet. `docker compose version`
must print 2.24 or newer.

## Tailscale

```sh
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --hostname=pi@<your-pi>
```

The hostname is worth choosing deliberately and once. It becomes the `*.ts.net` origin the
app is served from, and an origin is what a PWA and a push subscription are both pinned to
— renaming it later means deleting and re-adding the app on both phones and granting
notification permission again, which on iOS is the permission there is no second chance at.

Two things must be on in the [admin console](https://login.tailscale.com/admin/dns) before
Serve can hand out a certificate: **MagicDNS** and **HTTPS Certificates**. Without them
there is no browser-trusted origin, so no service worker, so no notification.

While you are there, open the Pi under **Machines** and **disable key expiry** for it. The
default expires a node's key after a few months, after which the Pi silently drops off the
tailnet and the Diary stops being reachable one morning for a reason nothing on the Pi can
tell you.

## The checkout, and its `.env`

The repository is public, so the Pi needs no identity to clone it — no key to generate, no
credential on a machine sitting in a cupboard. What the Diary is actually about is not in
here: it lives in `.env`, which is written on the Pi by hand and never committed.

```sh
git clone https://github.com/H4ppyFlu/KiDiaryPublic.git ~/kidiary
cd ~/kidiary
cp .env.example .env
```

Cloning over https rather than ssh is the same decision from the other side: the Pi only ever
pulls, so it has nothing to prove to GitHub, and an unattended machine that cannot push is one
fewer thing that can go wrong in a direction nobody is watching.

The Pi's `.env` differs from the laptop's in four places:

```sh
# Makes a plain `docker compose ...` mean both files, so that the command which brings the
# Diary up here is the one muscle memory already types. On Linux the separator is a colon.
COMPOSE_FILE=docker-compose.yml:docker-compose.pi.yml

# The directory Syncthing mirrors to the laptop (ADR-0008). Outside the checkout, so that
# a `git clean` can never be the thing that deletes the backups.
BACKUP_DIR=/home/pi/kidiary-dumps

PIN=...                 # and SESSION_SECRET; the API refuses to start without both
CHILD_NAME=...          # recorded on the first start only, so get it right before it
```

`COOKIE_SECURE` is deliberately *not* among them — `docker-compose.pi.yml` sets it to
`true` unconditionally, so that no missing line and no file copied over from the laptop can
produce a year-long cookie that travels in the clear.

Generate the VAPID pair on the Pi and paste both halves in, then keep a copy somewhere
other than the Pi:

```sh
mkdir -p /home/pi/kidiary-dumps
docker compose run --rm --no-deps api python -m app.vapid
```

Losing that pair silently stops every device that has already subscribed, and no dump
contains it — `.env` is configuration, and a Pi restored without it starts every phone over.

## Up

```sh
docker compose up -d --build
docker compose config | grep -A4 'ports:'    # must say 127.0.0.1, and say it once
```

That second line is worth typing the first time. Compose *concatenates* port lists across
files rather than replacing them, so an override written without `!override` leaves the API
published on loopback **and** on every interface, and looks from the app exactly like one
that worked.

The first build is slow — a Vite build on a Pi, which is the cost ADR-0007 accepted
deliberately.

The Pi comes up with an empty Diary, migrated and seeded. To carry the laptop's Answers
over instead, copy a dump across and follow [*Actually restoring*](backups.md#actually-restoring)
before the first `up` — restoring over a database the API has already seeded is the case
that section's `drop database` exists for.

## Publishing it

```sh
tailscale serve --bg 8000
tailscale serve status        # the https://<host>.ts.net URL, and "(tailnet only)"
```

`serve`, never `funnel`. The two commands are one word apart and the difference is the
entire ADR: Serve publishes to the tailnet, Funnel publishes to the internet.

Then run the checks:

```sh
sh deploy/check.sh
```

It asks the machine the things this section claims — that the port is on loopback and the
LAN cannot reach it, that Serve is publishing to 127.0.0.1:8000 and says "(tailnet only)",
that the app answers over https and `/api/health` answers `401` behind the PIN, that last
night's dump is on disk, and that docker and tailscaled both start at boot. It ends by
printing what it cannot know, which is the half of the ticket that happens on two phones.

## Both phones

Each phone joins the tailnet, opens the `https://<host>.ts.net` URL, and adds the app to
its home screen — on iOS via **Share → Add to Home Screen**, which is the only way iOS will
deliver Web Push at all. Then open it *from the home screen*, type the PIN, say which Parent
is holding it, and say yes to the notification on the screen that follows.

Confirm the evening notification by setting a time a few minutes out under `Erinnerung`,
waiting for it, and tapping it: it must open the app on the Prompt the notification showed,
not a fresh one. Do this on each phone separately — permission and subscription are both per
device, and one says nothing about the other.

## Syncthing

```sh
sudo apt install -y syncthing
sudo systemctl enable --now syncthing@"$USER"
```

Its interface binds to loopback and is best left there; reach it from the laptop over an SSH
tunnel rather than by publishing a second thing:

```sh
ssh -L 8384:127.0.0.1:8384 pi@<your-pi>      # then open http://localhost:8384 on the laptop
```

Add `BACKUP_DIR` as a folder, share it with the laptop, and set the Pi's copy to **Send
Only**. That last setting is the one that matters: a two-way folder means a deletion on the
laptop is a deletion on the Pi, and the directory being protected here is the one that
exists for the morning everything else is gone.

## After a power cut

Nothing on the Pi should need a person. `restart: unless-stopped` brings the four containers
back once the Docker daemon is up, systemd starts the daemon, and Serve's configuration is
kept by `tailscaled` rather than by the shell that ran it. The way to believe that is to
take the power away:

```sh
sudo reboot
# wait, then, from the laptop:
ssh pi@<your-pi> 'cd ~/kidiary && sh deploy/check.sh'
```

## When Tailscale is off on a phone

The notification still arrives, and the app cannot load. Both halves are expected, and they
are expected for the same reason: a push is delivered by Apple's or Google's servers and
never needs the phone to reach the Pi, while the Diary itself lives only on the tailnet.
So a phone with Tailscale off is woken by a Prompt it cannot open — and what it shows when
tapped is Kidiary's own screen saying it cannot reach the Diary, not the browser's error
page, because the service worker precaches the app shell. Turning Tailscale back on and
reopening is the whole of the fix.
