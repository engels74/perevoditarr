import pytest

from perevoditarr.core.settings import AppSettings, SettingsError, load_settings


def test_defaults_without_env() -> None:
    settings = load_settings(environ={})
    assert settings == AppSettings()
    assert settings.env == "dev"
    assert settings.database_url.startswith("sqlite+aiosqlite")


def test_prefix_and_list_parsing() -> None:
    settings = load_settings(
        environ={
            "PEREVODITARR_ENV": "prod",
            "PEREVODITARR_DATABASE_URL": "postgresql+asyncpg://app:pw@db/app",
            "PEREVODITARR_SECRET_KEY": "s" * 32,
            "PEREVODITARR_LOG_LEVEL": "debug",
            "PEREVODITARR_TRUSTED_PROXIES": "10.0.0.0/8, 192.168.1.1",
            "UNRELATED": "ignored",
        }
    )
    assert settings.env == "prod"
    assert settings.log_level == "DEBUG"
    assert settings.trusted_proxies == ("10.0.0.0/8", "192.168.1.1")


def test_rejects_unknown_db_scheme() -> None:
    with pytest.raises(SettingsError, match="DATABASE_URL scheme"):
        _ = load_settings(environ={"PEREVODITARR_DATABASE_URL": "mysql://x/y"})


def test_prod_requires_secret_key() -> None:
    with pytest.raises(SettingsError, match="SECRET_KEY"):
        _ = load_settings(environ={"PEREVODITARR_ENV": "prod"})
    with pytest.raises(SettingsError, match="SECRET_KEY"):
        _ = load_settings(
            environ={"PEREVODITARR_ENV": "prod", "PEREVODITARR_SECRET_KEY": "short"}
        )


def test_rejects_invalid_trusted_proxy_cidr() -> None:
    with pytest.raises(SettingsError, match="TRUSTED_PROXIES"):
        _ = load_settings(environ={"PEREVODITARR_TRUSTED_PROXIES": "not-a-network"})


def test_rejects_invalid_env_value() -> None:
    with pytest.raises(SettingsError):
        _ = load_settings(environ={"PEREVODITARR_ENV": "staging"})
