"""Write THIRD_PARTY_LICENSES.txt for a build: every package the app ships, with its
licence text, plus the native programs bundled beside them.

Only what the installed app needs at runtime is listed: PageVoice's dependencies and the
`gui` extra, followed recursively. Test, build and round-trip tools aren't shipped, so
they aren't listed.

    uv run python tools/third_party.py dist/THIRD_PARTY_LICENSES.txt
"""

import contextlib
import re
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Programs bundled outside Python packages, or inside one under its own licence.
NATIVE = [
    ("ffmpeg 8.1.3 (LGPL-only build)", "LGPL-2.1-or-later",
     "https://ffmpeg.org/releases/ffmpeg-8.1.3.tar.xz (also attached to each release)"),
    ("LAME 3.100", "LGPL-2.0-or-later",
     "https://lame.sourceforge.io/ (lame-3.100.tar.gz attached to each release)"),
    ("espeak-ng 1.52.0 (inside espeakng-loader)", "GPL-3.0-or-later",
     "https://github.com/espeak-ng/espeak-ng/tree/1.52.0 (attached to each release)"),
    ("Qt 6 (inside PySide6-Essentials)", "LGPL-3.0", "https://download.qt.io/official_releases/qt/"),
    ("PortAudio (inside sounddevice)", "MIT", "https://github.com/PortAudio/portaudio"),
    ("libsndfile (inside soundfile)", "LGPL-2.1-or-later", "https://github.com/libsndfile/libsndfile"),
]  # fmt: skip
LICENSE_FILE = re.compile(r"(^|/)(licen[cs]e|copying|notice|authors)[^/]*$", re.I)


def _name(requirement: str) -> str | None:
    """'numpy>=2.0; extra == "x"' -> 'numpy', or None if it's for an extra we don't ship."""
    req, _, marker = requirement.partition(";")
    if "extra" in marker:
        return None
    return re.split(r"[\s<>=!~\[(]", req.strip(), maxsplit=1)[0]


def runtime_packages() -> list[metadata.Distribution]:
    """PageVoice's runtime dependencies plus the gui extra, and theirs, recursively."""
    own = metadata.distribution("pagevoice")
    todo = []
    for requirement in own.requires or []:
        req, _, marker = requirement.partition(";")
        if "extra" not in marker or '"gui"' in marker or "'gui'" in marker:
            todo.append(re.split(r"[\s<>=!~\[(]", req.strip(), maxsplit=1)[0])
    seen: dict[str, metadata.Distribution] = {}
    while todo:
        name = todo.pop()
        key = name.lower().replace("_", "-")
        if key in seen:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue  # a dependency for another platform
        seen[key] = dist
        todo += [n for n in map(_name, dist.requires or []) if n]
    return sorted(seen.values(), key=lambda d: d.metadata["Name"].lower())


def _license(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression
    classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or []
                   if c.startswith("License ::")]  # fmt: skip
    text = (meta.get("License") or "").strip()
    return "; ".join(classifiers) or (text.splitlines()[0] if text else "see licence text")


def _texts(dist: metadata.Distribution) -> list[str]:
    out = []
    for file in dist.files or []:
        if LICENSE_FILE.search(str(file)):
            with contextlib.suppress(OSError):  # listed in RECORD but not on disk
                text = Path(dist.locate_file(file)).read_text("utf-8", "replace")
                out.append(f"--- {file}\n{text}")
    return out


def main(path: str) -> int:
    lines = [
        "PageVoice is free software under the GNU General Public License v3.0 (LICENSE).",
        "It includes the third-party software listed below, each under its own licence.",
        "",
        "== Programs and libraries bundled outside Python packages ==",
        "",
    ]
    for name, licence, source in NATIVE:
        lines += [f"{name}", f"  Licence: {licence}", f"  Source:  {source}", ""]
    packages = runtime_packages()
    lines += [f"== Python packages ({len(packages)}) ==", ""]
    for dist in packages:
        lines.append(f"{dist.metadata['Name']} {dist.version}: {_license(dist)}")
    lines += ["", "== Licence texts ==", ""]
    for dist in packages:
        texts = _texts(dist)
        lines += [f"======== {dist.metadata['Name']} {dist.version} ========"]
        lines += texts or [f"(no licence file shipped; licence: {_license(dist)})"]
        lines.append("")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(packages)} packages -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "dist/THIRD_PARTY_LICENSES.txt"))
