"""Play a short WAV (pronunciation previews) without a multimedia library.

PySide6-Essentials has no QtMultimedia, and a preview doesn't need one: Windows has
winsound in the standard library, and Linux desktops ship a command-line player.
"""

import os
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QCoreApplication

LINUX_PLAYERS = (["pw-play"], ["paplay"], ["aplay", "-q"])


class PlaybackError(RuntimeError):
    """No way to play sound here. The message is plain language."""


def player_command(path: Path) -> list[str] | None:
    for command in LINUX_PLAYERS:
        if shutil.which(command[0]):
            return [*command, str(path)]
    return None


def play(path: Path) -> None:
    """Start playing the file and return at once."""
    if os.name == "nt":
        import winsound

        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        return
    command = player_command(path)
    if command is None:
        raise PlaybackError(QCoreApplication.translate(
            "Playback",
            "No sound player was found (PipeWire, PulseAudio or ALSA), so the preview can't "
            "be played.",
        ))  # fmt: skip
    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
