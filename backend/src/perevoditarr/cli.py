"""Admin CLI entrypoint.

Phase 0 stub: real subcommands (user create, doctor run, resync) arrive with their
modules in later phases.
"""

import argparse
from importlib.metadata import version


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="perevoditarr",
        description="Perevoditarr admin CLI",
    )
    _ = parser.add_argument(
        "--version",
        action="version",
        version=f"perevoditarr {version('perevoditarr')}",
    )
    _ = parser.parse_args()
    parser.print_help()
