"""Small command line for driving the engine during development and testing."""

import argparse

from pagevoice import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pagevoice", description=__doc__)
    parser.add_argument("--version", action="version", version=f"pagevoice {__version__}")
    parser.parse_args(argv)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
