---
name: add-dependency
description: Add a Python package to PageVoice. Use before any uv add / pip install. Checks the package and everything it pulls in for GPL-3.0-compatible licenses in a throwaway environment first, then installs and records it in docs/DECISIONS.md.
---

# Add a dependency

PageVoice ships under GPL-3.0. AGPL, non-commercial, proprietary and unknown licenses can't ship. PyMuPDF (`fitz`), EbookLib and PyTorch are banned outright (docs/DECISIONS.md D3, D5).

## 1. Justify it

- Say what it's for, and why the standard library or an existing dependency won't do.
- Decide its group:
  - **runtime:** `[project] dependencies`, which ships in the installer.
  - **`gui`:** optional extra.
  - **`dev`**, or a named dev group such as `roundtrip`: never shipped.
- **Installer size:** a runtime package that pulls in PyTorch, CUDA, or anything over about 20 MB needs the owner's OK first.

## 2. Check the license before it touches the project

Vet it in a throwaway environment that holds only that package and its dependencies:

```
uv run --isolated --no-project --with <package> --with pip-licenses python tools/check_licenses.py
uv run --isolated --no-project --with <package> --with pip-licenses python -m piplicenses --from=mixed
```

- **If the check fails:** stop. Report which package and license failed. Don't install it, and suggest an alternative.
- **If it reports UNKNOWN:** look up the real license, either in the project's repository LICENSE file or on PyPI at `https://pypi.org/pypi/<name>/json`. If it's genuinely fine, it goes in `REVIEWED` in `tools/check_licenses.py`, and that change needs the owner's OK.
- **For runtime packages:** also check what it pulls in with `uv tree --package <package>` after a dry resolve, and watch for large transitive dependencies.

## 3. Install

The owner approves this command; it's in the permission ask list:

```
uv add <package>                 # runtime
uv add --group dev <package>     # dev only
uv add --optional gui <package>  # GUI extra
```

Then confirm the project as a whole still passes:

```
uv run python tools/check_licenses.py
uv run pytest
```

## 4. Record it

Add a row to the dependency log at the bottom of `docs/DECISIONS.md`: date, package, license, group, why. If a decision entry names the package (e.g. pypdfium2 for D5), mention it there too.
