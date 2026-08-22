# Vendor manifest (D8)

A vendored copy of ucc-contracts contains exactly:

  ucc_contracts/     schemas/     fixtures/     transitions/
  pyproject.toml     README.md    VENDOR-MANIFEST.md

Excluded, deliberately:
  tests/         — each consuming repo runs its own tests/contracts/ harness
                   against the vendored fixtures/; duplicating this suite three
                   times creates three places for it to rot.
  .gitignore     — repo hygiene for this repo, meaningless inside a vendor tree.
  .git/, *.egg-info/, __pycache__/ — build/VCS artifacts, never vendored.

Equality rule: every tag-backed file in the export set is byte-identical to the
pinned tag; this post-tag manifest matches the authoritative root copy; no
excluded path is tracked; all consuming repos' copies are mutually identical.

> This manifest post-dates the immutable v0.2.0 tag. It is release metadata, not a tag
> member. Vendor equality is verified by comparing each vendored export-set file to the
> authoritative root and to the other vendors — NOT by tag membership. Moving v0.2.0 to
> include this file would rewrite release history and is prohibited.
