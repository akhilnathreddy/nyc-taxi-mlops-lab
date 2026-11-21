# 002: Image tag scheme: sha-<short sha>

Stage: S0 · Date: 2026-11-21 · Author: akhilnathreddy · Drafted by agent: yes

## Choice

Every push to `main` that passes `make check` builds one image tagged `sha-<first 7 hex of the commit sha>` (e.g. `ghcr.io/akhilnathreddy/nyc-taxi-mlops-lab/app:sha-127a274`). Tags are never reused or moved. A deploy and a rollback both point at one of these tags; rollback is `cd.yaml` run by hand with an earlier tag.

## Rejected alternative

A mutable tag such as `latest` (or `main`), moved to the newest build on every push, with hosts always pulling it.

## Why

- A rollback needs something to point at. `latest` only ever names the newest build, so "go back" means rebuilding an old commit or digging digests out of GHCR, under pressure. With `sha-<short sha>` the previous version is still there under a name I can type.
- The running version is identifiable: `/version` returns `image_tag` and `git_sha`, and the CD smoke test checks that the tag and the sha agree, so "what's live?" maps directly to a commit on `main`.
- A mutable tag makes deploys non-reproducible: two `docker compose pull`s of `latest` minutes apart can run different code, and a restart after a session refresh could silently pick up a newer image than the one that was smoke-tested.
- Cost I accept: tags aren't human-friendly (no "v1.3"), and GHCR accumulates one image per main commit, so old ones need pruning eventually. 7 hex characters can collide in principle; at this repo's size that's negligible, and `cd.yaml` validates the exact `sha-<7 hex>` shape.

## What would show this was wrong

- Two commits on `main` whose short shas collide (the push would overwrite an existing tag).
- Someone needing to know "which release" from the tag alone (e.g. a changelog or a client pinning versions), which would argue for semver on top.
- GHCR storage or listing becoming unmanageable because nothing prunes old `sha-*` tags.
