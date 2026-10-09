---
name: release
description: Cut a PageVoice release. Bump the version on a release/vX.Y.Z branch, merge it through a PR (main is protected), tag the merge commit, watch CI, and confirm the Windows installer and Linux AppImage are attached to the GitHub release and signed.
disable-model-invocation: true
argument-hint: "<version, e.g. 1.2.0>"
---

# Release PageVoice $ARGUMENTS

`main` is protected: no direct pushes, no force pushes, and CI must pass on a PR. The version bump goes through a PR like everything else, and the tag goes on the merge commit.

Stop and report at the first step that fails. Never retag, force-push, or delete a tag or release without the owner saying so.

## 1. Preflight on an up-to-date main

```
git switch main
git pull --ff-only
git status                      # must be clean
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run python tools/check_licenses.py
```

## 2. Release branch: version and changelog

```
git switch -c release/v$ARGUMENTS
```

1. Set `__version__ = "$ARGUMENTS"` in `src/pagevoice/__init__.py`. It's the single source; the package version is read from it.
2. In `CHANGELOG.md`, move the `[Unreleased]` items under `## [$ARGUMENTS] - <today>`, written for users (what changed for them, not internal refactors), and leave an empty `[Unreleased]`.
3. Commit with the message `Version $ARGUMENTS`. No AI attribution.

## 3. PR, CI, merge

The owner approves the push and the merge.

```
git push -u origin release/v$ARGUMENTS
gh pr create --base main --title "Version $ARGUMENTS" --body "<the new CHANGELOG section>"
gh pr checks --watch --fail-fast
gh pr merge --merge --delete-branch
```

Use a merge commit, not a squash, so the tagged commit on `main` is the merge itself. If a check fails, show it (`gh run view <run-id> --log-failed`) and stop.

## 4. Tag the merge commit on main

```
git switch main
git pull --ff-only
git log -1 --format='%H %s'      # must be the merge of release/v$ARGUMENTS
git tag v$ARGUMENTS
git push origin v$ARGUMENTS
```

## 5. Watch the release build

```
gh run list --workflow release.yml --limit 3
gh run watch <run-id> --exit-status
```

If a job fails, show the failing step's log (`gh run view <run-id> --log-failed`) and stop.

## 6. Confirm the release

```
gh release view v$ARGUMENTS --json assets --jq '.assets[].name'
```

- **Expected assets:** the Windows installer (`PageVoice-$ARGUMENTS-setup.exe`) and the Linux AppImage (`PageVoice-$ARGUMENTS-x86_64.AppImage`).
- **Check the Windows signature:** download the installer to the scratchpad and run, in PowerShell:
  `Get-AuthenticodeSignature <path> | Format-List Status, SignerCertificate`
  - Expect `Status: Valid` once SignPath is configured.
  - If the `SIGNPATH_API_TOKEN` secret doesn't exist yet, the build is unsigned by design. Say so plainly; don't report it as signed.
- **Check the AppImage:** it is attached, and its size is in line with the previous release.

## 7. Report

- Version, PR link, release URL and the assets with their sizes.
- Signed or unsigned.
- Anything that differed from the previous release.
