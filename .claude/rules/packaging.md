---
paths:
  - "packaging/**"
  - ".github/workflows/**"
---

# Packaging and CI rules

## PyInstaller

**One-folder mode only.** Never `--onefile`: antivirus tools flag it constantly.

## Windows

The one-folder build goes inside an Inno Setup installer.

## Linux

- An AppImage, built on `runs-on: ubuntu-22.04` so it runs on older distros. Don't bump the runner to get newer libraries.
- No .deb or Flatpak in v1.

## ffmpeg

- **Build it in CI; never download it at runtime or use the system copy.** It is LGPL-only: no `--enable-gpl`, no `--enable-nonfree`.
- **Enable only what we use:**
  - Encoders: native `aac` and `libmp3lame`.
  - Muxers: `ipod`/`mp4` (M4B) and `mp3`.
  - Demuxers: `wav`, `flac`, `concat`, `ffmetadata` and image input for cover art.
  - Protocols: `file` and `pipe`.
- The binary is bundled and signed with the app.

## Release workflow

- Mirror `N-Shovel/folder-tracker/.github/workflows/release.yml`: on a `v*` tag, build the Windows and Linux jobs, and both attach to the same GitHub release. Handle the race where the other job created the release first.
- **SignPath steps:**
  - Run only when `SIGNPATH_API_TOKEN` is set (`if: env.SIGNPATH_API_TOKEN != ''`).
  - The organization ID comes from `vars.SIGNPATH_ORGANIZATION_ID`.
  - Without them, the build ships unsigned.
- Sign everything Windows executes: the app exe, bundled DLLs where the SignPath policy allows, ffmpeg and the installer.

## CI workflow

- `.github/workflows/ci.yml` runs on every PR and every push to `main`.
- Branch protection on `main` requires its jobs **by name**: `checks (windows-latest)` and `checks (ubuntu-22.04)`. Renaming the job or changing the matrix silently blocks every PR until branch protection is updated to match. Do both in the same change, and tell the owner.

## Model and secrets

- The model and voices files are never in the installer. They are downloaded on first run, checked against the manifest.
- Secrets live only in GitHub repository secrets. Never write a token into a file, log or workflow.
