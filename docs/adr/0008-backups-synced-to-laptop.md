# Backups are nightly dumps synced to the laptop

A nightly job runs `pg_dump` into a directory on the Pi, retaining the last several dumps. That directory is mirrored to the owner's laptop with Syncthing over the tailnet, so a copy lands on separate hardware whenever the laptop is online.

Syncthing rather than a scheduled copy because the Pi cannot know when the laptop is awake; Syncthing is built for "sync whenever both are up" and needs no scheduling or presence detection on either side. A push job from the Pi would have to detect the laptop and retry.

## Consequences

This is **off-device, not off-site**: it fully covers disk failure, filesystem corruption and the Pi dying, but a fire or burglary takes both machines. Closing that gap means adding one more sync destination later, which is why it does not block v1.

The dumps are not encrypted. They never leave two personally-owned machines and travel over an encrypted tailnet, so a passphrase would be one more thing to lose. **If a cloud destination is ever added, encryption becomes required.**

Backups ship in v1, before real entries exist — deferring them risks losing exactly the data the project exists to keep. A restore into a throwaway database must be tested once; an untested backup is a hypothesis.
