"""Typed application settings loaded from the environment (P1-T1).

Fail-fast: invalid values abort boot with a clear error instead of surfacing
later as runtime misbehavior.
"""

import ipaddress
import os
from collections.abc import Mapping
from typing import Literal

import msgspec

ENV_PREFIX = "PEREVODITARR_"

_ALLOWED_DB_SCHEMES = frozenset({"postgresql+asyncpg", "sqlite+aiosqlite"})
_MIN_SECRET_KEY_LENGTH = 32


class SettingsError(Exception):
    """Raised when the environment yields an invalid configuration."""


class AppSettings(msgspec.Struct, kw_only=True, frozen=True):
    env: Literal["dev", "prod"] = "dev"
    database_url: str = "sqlite+aiosqlite:///perevoditarr.db"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    secret_key: str | None = None
    trusted_proxies: tuple[str, ...] = ()
    spa_dir: str | None = None
    # Background loop intervals; 0 disables the respective loop.
    health_interval_seconds: int = 60
    sync_interval_seconds: int = 3600
    wanted_interval_seconds: int = 300
    doctor_interval_seconds: int = 86400
    discovery_interval_seconds: int = 900
    reconcile_interval_seconds: int = 600


_FIELD_NAMES = frozenset(field.name for field in msgspec.structs.fields(AppSettings))
_LIST_FIELDS = frozenset({"trusted_proxies"})


def load_settings(environ: Mapping[str, str] | None = None) -> AppSettings:
    source = os.environ if environ is None else environ
    raw: dict[str, object] = {}
    for key, value in source.items():
        if not key.startswith(ENV_PREFIX):
            continue
        name = key.removeprefix(ENV_PREFIX).lower()
        if name not in _FIELD_NAMES:
            continue
        if name in _LIST_FIELDS:
            raw[name] = tuple(part.strip() for part in value.split(",") if part.strip())
        elif name == "log_level":
            raw[name] = value.upper()
        else:
            raw[name] = value
    try:
        settings = msgspec.convert(raw, type=AppSettings, strict=False)
    except msgspec.ValidationError as error:
        raise SettingsError(f"invalid environment configuration: {error}") from error
    _validate(settings)
    return settings


def _validate(settings: AppSettings) -> None:
    scheme = settings.database_url.partition("://")[0]
    if scheme not in _ALLOWED_DB_SCHEMES:
        raise SettingsError(
            f"{ENV_PREFIX}DATABASE_URL scheme must be one of "
            + f"{sorted(_ALLOWED_DB_SCHEMES)}, got {scheme!r}"
        )
    if settings.env == "prod" and (
        settings.secret_key is None or len(settings.secret_key) < _MIN_SECRET_KEY_LENGTH
    ):
        raise SettingsError(
            f"{ENV_PREFIX}SECRET_KEY of at least {_MIN_SECRET_KEY_LENGTH} characters "
            + "is required when PEREVODITARR_ENV=prod"
        )
    for field_name in (
        "health_interval_seconds",
        "sync_interval_seconds",
        "wanted_interval_seconds",
        "doctor_interval_seconds",
        "discovery_interval_seconds",
        "reconcile_interval_seconds",
    ):
        if getattr(settings, field_name) < 0:
            raise SettingsError(
                f"{ENV_PREFIX}{field_name.upper()} must be >= 0 (0 disables)"
            )
    for cidr in settings.trusted_proxies:
        try:
            _ = ipaddress.ip_network(cidr, strict=False)
        except ValueError as error:
            raise SettingsError(
                f"{ENV_PREFIX}TRUSTED_PROXIES entry {cidr!r} is not a valid CIDR"
            ) from error
