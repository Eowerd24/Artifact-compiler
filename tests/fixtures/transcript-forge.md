---
kind: transcript
source: claude
adapter: passthrough-v1
title: forge provisioning
turns: 6
---
<!-- turn 1 role=user ts=2026-07-10T21:04:11Z -->
How do I join a fresh node to the tailnet with SSH restricted to port 2488?

```bash
# my manual steps so far
tailscale up
```

<!-- turn 2 role=assistant ts=2026-07-10T21:04:38Z -->
Here's a script that handles the join and locks SSH to the tailnet:

## Tailnet join

```bash
#!/usr/bin/env bash
# join node to tailnet v1
sudo tailscale up --ssh
ufw allow in on tailscale0 to any port 2488
```

<!-- turn 3 role=user ts=2026-07-10T21:06:02Z -->
Add idempotency and error handling.

<!-- turn 4 role=assistant ts=2026-07-10T21:06:40Z -->
Updated version:

```bash
#!/usr/bin/env bash
# join node to tailnet v2
set -euo pipefail
if ! tailscale status >/dev/null 2>&1; then
  sudo tailscale up --ssh
fi
ufw allow in on tailscale0 to any port 2488
```

<!-- turn 5 role=user ts=2026-07-10T21:08:00Z -->
What does a successful run look like?

<!-- turn 6 role=assistant ts=2026-07-10T21:08:21Z -->
### Verify

```console
$ tailscale status
100.64.0.7  forge  linux  -
```

```json
{"node": "forge", "ssh_port": 2488}
```
