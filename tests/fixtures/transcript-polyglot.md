---
kind: transcript
schema: 1
source: markdown
adapter: markdown-v1
conversation_id: null
title: polyglot ops
exported_at: null
turns: 4
---

<!-- turn 1 role=user -->
Give me tooling to audit disk usage across the fleet.

```python
# my broken attempt
print(disk)
```

<!-- turn 2 role=assistant -->
## Disk audit

```bash
#!/usr/bin/env bash
# disk audit
du -sh /var/* | sort -h | tail -n 5
```

## Disk audit python

```py
import shutil
total, used, free = shutil.disk_usage("/")
print(f"{used / total:.0%} used")
```

## Disk audit powershell

```pwsh
Get-PSDrive -PSProvider FileSystem | Select-Object Name, Used, Free
```

## Largest tables

```postgres
SELECT relname, pg_total_relation_size(relid) AS bytes
FROM pg_catalog.pg_statio_user_tables
ORDER BY bytes DESC
LIMIT 10;
```

## Summarize audit

```prompt
You are an SRE. Summarize the following disk audit output and list the
three hosts most at risk of filling up.
```

## Disk full runbook

```md
# Disk full runbook

1. Run the disk audit script.
2. Rotate logs: `sudo logrotate -f /etc/logrotate.conf`.
3. Escalate if usage stays above 90%.
```

<!-- turn 3 role=user -->
What does the output look like?

<!-- turn 4 role=assistant -->
### Sample output

```console
$ ./disk-audit.sh
1.2G /var/log
```

```
4.0K /var/tmp
```

```yaml
threshold: 90
```
