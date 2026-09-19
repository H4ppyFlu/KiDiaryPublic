# Hosted privately on a home Raspberry Pi via Tailscale Serve

Kidiary runs on a Raspberry Pi 4 at home and is published to the family's tailnet with Tailscale Serve — never to the public internet. Tailscale provisions a browser-trusted certificate on a stable `*.ts.net` hostname, which satisfies the service worker's requirement for a secure context on a stable origin without a domain purchase, port forwarding, or a public tunnel.

## Considered Options

Public exposure via Tailscale Funnel or a Cloudflare Tunnel with a purchased domain was the obvious alternative and was rejected: the content is a private archive about a child, and keeping it unreachable from the public internet removes that risk class rather than mitigating it with authentication.

Plain LAN hosting was rejected because it cannot work: a service worker will not register on an `http://192.168.x.x` origin, and a self-signed certificate would require installing a private root CA on both phones and would still break away from home.

## Consequences

Both parents' phones must run Tailscale, including the Android one. If the VPN is off, the evening notification still arrives — push is delivered by APNs/FCM and never requires the phone to reach the Pi — but tapping it opens an app that cannot load.

Because only authenticated tailnet devices can reach the app at all, authentication inside the app is a shared PIN rather than per-parent accounts or invite links.
