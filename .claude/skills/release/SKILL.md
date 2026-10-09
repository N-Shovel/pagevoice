---
name: release
description: Cut a PageVoice release. Bump the version, update the changelog, tag, push, watch CI, and confirm the Windows installer and Linux AppImage are attached to the GitHub release and signed.
disable-model-invocation: true
argument-hint: "<version, e.g. 1.2.0>"
---

# Release PageVoice $ARGUMENTS

Stop and report at the first step that fails. Never retag or force-push without the owner saying so.

## 1. Preflight

```
git status                      # must be clean
git branch --show-current       # must be main
git fetch origin && git status  # must be up to date with origin/main
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run python tools/check_licenses.py
```

## 2. Version and changelog

1. Set `__version__ = "$ARGUMENTS"` in `src/pagevoice/__init__.py`. It's the single source; the package version is read from it.
2. In `CHANGELOG.md`, move the `[Unreleased]` items under `## [$ARGUMENTS] - <today>`, written for users (what changed for them, not internal refactors), and leave an empty `[Unreleased]`.
3. Commit with the message `Version $ARGUMENTS`. No AI attribution.

## 3. Tag and push

The owner approves each push.

```
git tag v$ARGUMENTS
git push origin main
git push origin v$ARGUMENTS
```

## 4. Watch CI

```
gh run list --workflow release.yml --limit 3
gh run watch <run-id> --exit-status
```

If a job fails, show the failing step's log (`gh run view <run-id> --log-failed`) and stop.

## 5. Confirm the release

```
gh release view v$ARGUMENTS --json assets --jq '.assets[].name'
```

- **Expected assets:** the Windows installer (`PageVoice-$ARGUMENTS-setup.exe`) and the Linux AppImage (`PageVoice-$ARGUMENTS-x86_64.AppImage`).
- **Check the Windows signature:** download the installer to the scratchpad and run, in PowerShell:
  `Get-AuthenticodeSignature <path> | Format-List Status, SignerCertificate`
  - Expect `Status: Valid` once SignPath is configured.
  - If the `SIGNPATH_API_TOKEN` secret doesn't exist yet, the build is unsigned by design. Say so plainly; don't report it as signed.
- **Check the AppImage:** it is attached, and its size is in line with the previous release.

## 6. Report

- Version, release URL and the assets with their sizes.
- Signed or unsigned.
- Anything that differed from the previous release.
