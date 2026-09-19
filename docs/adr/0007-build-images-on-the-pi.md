# Container images are built on the Pi, for now

Deployment is `git pull` and a Docker Compose build on the Raspberry Pi itself. Images use a multi-stage Dockerfile so that Node and `node_modules` exist only in the build stage and never in the final image.

## Considered Options

Cross-building arm64 images on the x86 laptop with `docker buildx` was rejected: the emulated build is frequently slower than building natively on the Pi, and it adds a container registry to the setup for no gain at this size.

Building in GitHub Actions and having the Pi pull from GHCR is the better long-term answer — no build load on either machine, and it exercises the CI half of the containers goal. It was deferred rather than rejected, because it adds a registry, a workflow file and secrets before there is anything to deploy.

## Consequences

Every deploy runs `npm install` and a Vite build on a 2GB Pi with Postgres already resident. This is expected to be slow and may hit memory pressure.

**Trigger to revisit:** when deploys become slow enough to be annoying, or a build actually fails on memory, move to GitHub Actions. That work is tracked as a GitHub issue.
