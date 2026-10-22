"""Licences and sources for a build: what the app ships, and what copyleft needs with it.

    uv run python tools/third_party.py dist/THIRD_PARTY_LICENSES.txt
    uv run python tools/third_party.py --sources dist/sources

The first writes every bundled package with its licence text, the native libraries with
their exact versions and source, and the full texts of the GPL, LGPL and MPL. The second
downloads, from the lock file, the source archive of every bundled package under a
copyleft licence (GPL, LGPL, MPL), checked against the lock file's SHA-256, and writes
SOURCES.txt pointing to the exact source of what has no archive on PyPI (Qt, PySide6).

Only what the installed app needs at runtime counts: PageVoice's dependencies and the
`gui` extra, followed recursively. Test, build and round-trip tools aren't shipped.
"""

import contextlib
import hashlib
import re
import sys
import tomllib
import urllib.request
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COPYLEFT = re.compile(r"\b(L?GPL|MPL)|general public|mozilla public", re.I)
LICENCE_TEXTS = ["LGPL-2.1.txt", "LGPL-3.0.txt", "MPL-2.0.txt"]  # GPL-3.0 is LICENSE


def native() -> list[tuple[str, str, str]]:
    """Programs bundled outside Python packages, or inside one under its own licence,
    with the exact versions of this build."""
    import soundfile
    from PySide6 import __version__ as pyside

    series = ".".join(pyside.split(".")[:2])
    sndfile = soundfile.__libsndfile_version__
    return [
        ("ffmpeg 8.1.3 (LGPL-only build)", "LGPL-2.1-or-later",
         "ffmpeg-8.1.3.tar.xz, attached to each release"),
        ("LAME 3.100 (inside ffmpeg, and inside libsndfile)", "LGPL-2.0-or-later",
         "lame-3.100.tar.gz, attached to each release"),
        ("espeak-ng 1.52.0 (inside espeakng-loader)", "GPL-3.0-or-later",
         "espeak-ng-1.52.0.tar.gz, attached to each release"),
        (f"Qt {pyside} (inside PySide6-Essentials)", "LGPL-3.0",
         f"https://download.qt.io/archive/qt/{series}/{pyside}/single/"
         f"qt-everywhere-src-{pyside}.tar.xz"),
        (f"PySide6 and shiboken6 {pyside}", "LGPL-3.0",
         f"pyside-setup-everywhere-src-{pyside}.tar.xz, attached to each release"),
        (f"libsndfile {sndfile} (inside soundfile)", "LGPL-2.1-or-later",
         f"libsndfile-{sndfile}.tar.xz, attached to each release"),
        ("mpg123 1.33.4 (inside libsndfile)", "LGPL-2.1",
         "mpg123-1.33.4.tar.bz2, attached to each release"),
        ("libogg 1.3.6, libvorbis 1.3.7, FLAC 1.5.0, Opus 1.5.2 (inside libsndfile)",
         "BSD-3-Clause", "https://xiph.org/downloads/ and https://opus-codec.org/"),
        ("PortAudio v19.7.0 on Windows (inside sounddevice); v19.6.0 in the Linux AppImage "
         "(Ubuntu 22.04's libportaudio2, see SYSTEM_LIBRARIES.txt)", "MIT",
         "https://github.com/PortAudio/portaudio"),
    ]  # fmt: skip


# Copyleft packages with no source archive on PyPI, and where their source is instead.
NO_SDIST = {"pyside6-essentials", "shiboken6"}  # pyside-setup-everywhere-src, attached


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
        "The source of every GPL, LGPL and MPL part is attached to each release on",
        "https://github.com/N-Shovel/pagevoice/releases (see SOURCES.txt there).",
        "",
        "== Programs and libraries bundled outside Python packages ==",
        "",
    ]
    for name, licence, source in native():
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
    for name in LICENCE_TEXTS:
        text = (ROOT / "packaging" / "licenses" / name).read_text(encoding="utf-8")
        lines += [f"======== Full text: {name[:-4]} ========", text, ""]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(packages)} packages -> {path}")
    return 0


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def sources(folder: str) -> int:
    """Download the copyleft packages' source archives named in uv.lock (SHA-256 checked)
    and write SOURCES.txt, which also points to what isn't on PyPI as source."""
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    locked = {_norm(p["name"]): p for p in tomllib.loads(
        (ROOT / "uv.lock").read_text(encoding="utf-8"))["package"]}  # fmt: skip
    notes = ["Source of the copyleft (GPL, LGPL, MPL) software in PageVoice's builds.", ""]
    for dist in runtime_packages():
        licence = _license(dist)
        if not COPYLEFT.search(licence):
            continue
        name, version = dist.metadata["Name"], dist.version
        sdist = locked.get(_norm(name), {}).get("sdist")
        if not sdist:
            if _norm(name) not in NO_SDIST:  # its source would ship nowhere: stop
                raise SystemExit(f"{name} is {licence} but has no source archive in uv.lock")
            notes.append(f"{name} {version} ({licence}): in pyside-setup-everywhere-src.")
            continue
        file = out / sdist["url"].rsplit("/", 1)[-1]
        if not file.is_file():
            urllib.request.urlretrieve(sdist["url"], file)
        expected = sdist["hash"].removeprefix("sha256:")
        if hashlib.sha256(file.read_bytes()).hexdigest() != expected:
            file.unlink()
            raise SystemExit(f"{file.name} doesn't match uv.lock's SHA-256")
        notes.append(f"{name} {version} ({licence}): {file.name}")
    notes += ["", "Not attached (about 1 GB); the exact source on Qt's long-term archive:"]
    notes += [f"  {name}: {source}" for name, _l, source in native() if "archive" in source]
    notes += [
        "",
        "Also attached (packaging/sources.sh): ffmpeg, LAME, espeak-ng, libsndfile, "
        "mpg123, pyside-setup; and SYSTEM_LIBRARIES.txt for the Linux AppImage.",
    ]
    (out / "SOURCES.txt").write_text("\n".join(notes) + "\n", encoding="utf-8")
    print(f"{len(notes)} lines -> {out / 'SOURCES.txt'}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--sources":
        raise SystemExit(sources(sys.argv[2]))
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "dist/THIRD_PARTY_LICENSES.txt"))
