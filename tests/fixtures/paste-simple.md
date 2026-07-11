# Homelab snippets

## Disk usage report

Prints the top consumers under /var.

```bash
#!/usr/bin/env bash
du -xh /var | sort -rh | head -20
```

## Rotate panel key

```bash
#!/usr/bin/env bash
# rotate nodepanel ssh key
ssh-keygen -t ed25519 -f ~/.ssh/nodepanel_ed25519 -N ""
```

Some helper in python:

```python
print("not a target")
```

And a mystery block:

```
echo mystery
```
