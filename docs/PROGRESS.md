# Progress

Claude Code keeps this file current. It updates it after every finished step and when it pauses at the usage limit (see [PAUSE_AND_RESUME.md](PAUSE_AND_RESUME.md)). Keep it short and up to date. The details live in git history and pull requests.

- **Last updated:** 2026-10-16
- **Milestone:** M0, Kokoro benchmark (not started)
- **Branch:** chore/usage-pause
- **State:** waiting for owner. The other states are: not started, working, paused (usage), done.

## Done
- Project setup, CI and branch protection (PR #1).

## In progress
- Installing claude-setup-usage (its README) on `chore/usage-pause`. Steps 1–5 are done, with the owner's changes to step 3: no git add/commit allow rules; push and `gh pr merge` are allowed; force-push and branch deletion are denied; D28 is updated to match. Fast tests pass. Not committed yet.

## Next step
- Finish the claude-setup-usage README: steps 6 and 7.
- Then start M0 (docs/SPEC.md §12) on a branch:
  1. Check that onnxruntime, PySide6, PyInstaller and misaki have Python 3.13 builds for Windows and Linux.
  2. Write `src/pagevoice/voice/model_manifest.proposed.json` for the owner to check.

## Waiting on the owner
- Nothing yet. M0 will need three things from him:
  - move the model manifest in
  - install espeak-ng for the phoneme-library comparison
  - do the blind A/B listening

## Notes for next time
- None.
