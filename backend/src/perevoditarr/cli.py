"""Admin CLI entrypoints.

Phase 1: export-openapi (feeds the frontend type generation, P1-T7).
Later phases add user management, doctor runs, and resync commands.
"""

import argparse
import sys
from importlib.metadata import version
from pathlib import Path
from typing import cast

import msgspec


def _export_openapi(out: str | None) -> None:
    from perevoditarr.app import create_app

    schema = create_app().openapi_schema.to_schema()
    payload = msgspec.json.format(msgspec.json.encode(schema), indent=2)
    if out is None:
        _ = sys.stdout.buffer.write(payload + b"\n")
    else:
        _ = Path(out).write_bytes(payload + b"\n")


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
    subparsers = parser.add_subparsers(dest="command")
    export = subparsers.add_parser(
        "export-openapi", help="dump the OpenAPI 3.1 schema as JSON"
    )
    _ = export.add_argument("--out", default=None, help="output file (default stdout)")

    args = parser.parse_args()
    # argparse.Namespace attributes are dynamically typed (Any); launder them
    # through `object` so the isinstance guard below is a real narrowing.
    command = cast("object", args.command)
    if command == "export-openapi":
        out = cast("object", args.out)
        _export_openapi(out if out is None or isinstance(out, str) else str(out))
    else:
        parser.print_help()
