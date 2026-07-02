"""Admin CLI entrypoints (`perevoditarr ...`).

Commands (P4-T3):
  export-openapi   dump the OpenAPI 3.1 schema (feeds frontend type generation)
  create-user      create an admin user headlessly (first-run or additional)
  run-doctor       run the configuration doctor and print findings
  resync           trigger a library + wanted resync for every enabled instance
  export-config    export presets/profiles/assignments/exclusions as JSON

The mutating commands open their own DB session from PEREVODITARR_DATABASE_URL,
mirroring the app's persistence config; upstream reads ride a short-lived
HTTP client registry that is always closed on exit.
"""

import argparse
import asyncio
import getpass
import os
import sys
from importlib.metadata import version
from pathlib import Path
from typing import cast

import msgspec

_PASSWORD_ENV = "PEREVODITARR_ADMIN_PASSWORD"


def _export_openapi(out: str | None) -> None:
    from perevoditarr.app import create_app

    schema = create_app().openapi_schema.to_schema()
    payload = msgspec.json.format(msgspec.json.encode(schema), indent=2)
    if out is None:
        _ = sys.stdout.buffer.write(payload + b"\n")
    else:
        _ = Path(out).write_bytes(payload + b"\n")


def resolve_password(cli_password: str | None) -> str:
    if cli_password:
        return cli_password
    env_password = os.environ.get(_PASSWORD_ENV)
    if env_password:
        return env_password
    return getpass.getpass("Password: ")


async def _create_user(
    *, username: str, password: str, email: str | None, is_admin: bool
) -> None:
    from perevoditarr.core.db import build_alchemy_config
    from perevoditarr.core.errors import PerevoditarrError
    from perevoditarr.core.settings import load_settings
    from perevoditarr.modules.auth.service import AuthService

    alchemy = build_alchemy_config(load_settings())
    async with alchemy.get_session() as session:
        service = AuthService(session)
        try:
            user = await service.create_user(
                username=username, password=password, email=email, is_admin=is_admin
            )
        except PerevoditarrError as error:
            print(f"error: {error}", file=sys.stderr)
            raise SystemExit(1) from error
    print(f"created user {user.username} (admin={user.is_admin})")


async def _run_doctor() -> None:
    from perevoditarr.core.db import build_alchemy_config
    from perevoditarr.core.http import HttpClientRegistry
    from perevoditarr.core.security import SecretBox, resolve_secret_key
    from perevoditarr.core.settings import load_settings
    from perevoditarr.core.sse import SseBus
    from perevoditarr.modules.doctor.service import DoctorService
    from perevoditarr.modules.instances import InstanceGateway
    from perevoditarr.modules.telemetry import TelemetryHealthRegistry

    settings = load_settings()
    alchemy = build_alchemy_config(settings)
    secret_box = SecretBox(resolve_secret_key(settings))
    registry = HttpClientRegistry()
    gateway = InstanceGateway(registry)
    try:
        async with alchemy.get_session() as session:
            service = DoctorService(
                session,
                secret_box,
                gateway,
                SseBus(),
                forward_auth_misconfigured=False,
                telemetry_health=TelemetryHealthRegistry(),
            )
            result = await service.run("manual")
    finally:
        await registry.aclose()
    by_severity: dict[str, int] = {"critical": 0, "warn": 0, "info": 0}
    for finding in result.findings:
        by_severity[finding.severity] = by_severity.get(finding.severity, 0) + 1
        print(f"[{finding.severity.upper()}] {finding.check_id}: {finding.message}")
    print(
        f"doctor: {by_severity['critical']} critical, "
        + f"{by_severity['warn']} warning, {by_severity['info']} info"
    )
    if by_severity["critical"] > 0:
        raise SystemExit(2)


async def _resync(instance_name: str | None) -> None:
    from perevoditarr.core.db import build_alchemy_config
    from perevoditarr.core.http import HttpClientRegistry
    from perevoditarr.core.security import SecretBox, resolve_secret_key
    from perevoditarr.core.settings import load_settings
    from perevoditarr.core.sse import SseBus
    from perevoditarr.modules.instances import InstanceGateway, InstancesService
    from perevoditarr.modules.mirror import MirrorSyncService

    settings = load_settings()
    alchemy = build_alchemy_config(settings)
    secret_box = SecretBox(resolve_secret_key(settings))
    registry = HttpClientRegistry()
    gateway = InstanceGateway(registry)
    synced = 0
    try:
        async with alchemy.get_session() as session:
            instances = InstancesService(session, secret_box)
            sync = MirrorSyncService(session, instances, gateway, SseBus(), None)
            for instance in await instances.list_bazarr():
                if not instance.enabled:
                    continue
                if instance_name is not None and instance.name != instance_name:
                    continue
                _ = await sync.sync_library(instance.id)
                _ = await sync.sync_wanted(instance.id)
                synced += 1
                print(f"resynced {instance.name}")
    finally:
        await registry.aclose()
    print(f"resync complete: {synced} instance(s)")


async def _export_config() -> bytes:
    from perevoditarr.core.db import build_alchemy_config
    from perevoditarr.core.http import HttpClientRegistry
    from perevoditarr.core.security import SecretBox, resolve_secret_key
    from perevoditarr.core.settings import load_settings
    from perevoditarr.modules.instances import InstanceGateway
    from perevoditarr.modules.policy import PolicyService

    settings = load_settings()
    alchemy = build_alchemy_config(settings)
    secret_box = SecretBox(resolve_secret_key(settings))
    registry = HttpClientRegistry()
    gateway = InstanceGateway(registry)
    try:
        async with alchemy.get_session() as session:
            service = PolicyService(session, secret_box, gateway)
            export = await service.export_policies()
    finally:
        await registry.aclose()
    payload = msgspec.json.format(msgspec.json.encode(export), indent=2)
    return payload


def str_arg(value: object) -> str | None:
    return value if isinstance(value, str) else None


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="perevoditarr", description="Perevoditarr admin CLI"
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

    create = subparsers.add_parser("create-user", help="create an admin user")
    _ = create.add_argument("--username", required=True)
    _ = create.add_argument(
        "--password",
        default=None,
        help=f"user password (or ${_PASSWORD_ENV}, or interactive prompt)",
    )
    _ = create.add_argument("--email", default=None)

    _ = subparsers.add_parser("run-doctor", help="run the configuration doctor")

    resync = subparsers.add_parser("resync", help="resync library + wanted state")
    _ = resync.add_argument(
        "--instance", default=None, help="limit to one Bazarr instance name"
    )

    export_config = subparsers.add_parser(
        "export-config", help="export presets/profiles/assignments as JSON"
    )
    _ = export_config.add_argument("--out", default=None)

    args = parser.parse_args()
    # argparse.Namespace attributes are dynamically typed (Any); launder them
    # through `object` so the isinstance guards below are real narrowings.
    command = cast("object", args.command)
    match command:
        case "export-openapi":
            _export_openapi(str_arg(cast("object", args.out)))
        case "create-user":
            username = str_arg(cast("object", args.username)) or ""
            password = resolve_password(str_arg(cast("object", args.password)))
            asyncio.run(
                _create_user(
                    username=username,
                    password=password,
                    email=str_arg(cast("object", args.email)),
                    is_admin=True,
                )
            )
        case "run-doctor":
            asyncio.run(_run_doctor())
        case "resync":
            asyncio.run(_resync(str_arg(cast("object", args.instance))))
        case "export-config":
            payload = asyncio.run(_export_config())
            out = str_arg(cast("object", args.out))
            if out is None:
                _ = sys.stdout.buffer.write(payload + b"\n")
            else:
                _ = Path(out).write_bytes(payload + b"\n")
                print(f"wrote {out}")
        case _:
            parser.print_help()
