"""Entry point of the packaged app (packaging/pagevoice.spec)."""

import sys

from pagevoice_gui.app import main

if __name__ == "__main__":
    sys.exit(main())
