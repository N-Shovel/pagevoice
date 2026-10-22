#!/usr/bin/env bash
# List the Ubuntu system libraries PyInstaller copied into the Linux build (Qt's X11
# plugin needs, PortAudio, D-Bus, …), with their package, exact version, licence and
# source, so the AppImage's licence notices cover them too (D38).
#
#   packaging/linux/system-libs.sh dist/PageVoice  > SYSTEM_LIBRARIES.txt
#
# Libraries that came inside a Python wheel aren't system libraries: their licences are
# in THIRD_PARTY_LICENSES.txt. Run on the build machine (ubuntu-22.04), after PyInstaller.
set -euo pipefail

APP="${1:?usage: system-libs.sh dist/PageVoice}"
echo "Ubuntu 22.04 libraries bundled in the PageVoice AppImage"
echo "Each package's source: https://launchpad.net/ubuntu/+source/<source>/<version>"
echo "(also: apt-get source <source>=<version> on Ubuntu 22.04)."
echo

SYSTEM_DIRS=(/lib/x86_64-linux-gnu /usr/lib/x86_64-linux-gnu)
declare -A seen
while IFS= read -r -d '' lib; do
  name="$(basename "$lib")"
  # Python extension modules come from wheels (their licences: THIRD_PARTY_LICENSES.txt).
  case "$name" in *.cpython-*|*.abi3.so) continue ;; esac
  # A system library is one that exists in Ubuntu's 64-bit library folders; ask dpkg
  # which package installed that exact file (not any file with the same name).
  pkg=""
  for dir in "${SYSTEM_DIRS[@]}"; do
    path="$(find "$dir" -maxdepth 2 -name "$name" -print -quit 2>/dev/null || true)"
    [ -n "$path" ] || continue
    pkg="$(dpkg -S "$(readlink -f "$path")" 2>/dev/null | head -1 | cut -d: -f1 || true)"
    [ -n "$pkg" ] || pkg="$(dpkg -S "$path" 2>/dev/null | head -1 | cut -d: -f1 || true)"
    [ -n "$pkg" ] && break
  done
  [ -n "$pkg" ] || continue
  [ -z "${seen[$pkg]:-}" ] || { seen[$pkg]+=" $name"; continue; }
  seen[$pkg]="$name"
done < <(find "$APP" -name '*.so*' -type f -print0)

for pkg in $(printf '%s\n' "${!seen[@]}" | sort); do
  version="$(dpkg-query -W -f='${Version}' "$pkg")"
  source="$(dpkg-query -W -f='${source:Package}' "$pkg")"
  copyright="/usr/share/doc/$pkg/copyright"
  licences="$( (grep -E '^License:' "$copyright" 2>/dev/null || true) | sed 's/License: *//' \
    | sort -u | paste -sd ', ' -)"
  echo "$pkg $version (source package $source): ${licences:-see /usr/share/doc/$pkg/copyright}"
  echo "  files: ${seen[$pkg]}"
  echo "  source: https://launchpad.net/ubuntu/+source/$source/$version"
done
