"""LDAP bind authentication (P5-T2, FR-A4).

ldap3 is synchronous, so the bind/search sequence runs in a worker thread
(asyncio.to_thread) — never blocking the event loop (Conventions §0). LDAP is a
*fallback* authenticator: the built-in password check runs first, so local
users keep working when LDAP is enabled.

ldap3 ships no type information, so its surface is confined to the small typed
Protocol boundary below; the two `cast(...)` lines are the only untyped seams.
"""

import asyncio
from collections.abc import Callable
from typing import Protocol, cast

import ldap3
import msgspec
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars

from perevoditarr.core.logging import get_logger
from perevoditarr.modules.auth.schemas import LdapProviderSettings

_logger = get_logger()


class LdapIdentity(msgspec.Struct, kw_only=True, frozen=True):
    username: str
    email: str | None = None


class _LdapAttr(Protocol):
    value: object


class _LdapEntry(Protocol):
    entry_dn: str

    def __getitem__(self, name: str) -> _LdapAttr: ...


class _LdapConnection(Protocol):
    entries: list[_LdapEntry]

    def bind(self) -> bool: ...
    def unbind(self) -> None: ...
    def start_tls(self) -> bool: ...
    def search(
        self, search_base: str, search_filter: str, attributes: list[str]
    ) -> bool: ...


# The only untyped seams: grab ldap3's factories as typed callables once.
_make_server = cast("Callable[..., object]", ldap3.Server)
_make_connection = cast("Callable[..., _LdapConnection]", ldap3.Connection)
_escape_filter = cast("Callable[[str], str]", escape_filter_chars)


def _entry_email(entry: _LdapEntry, attribute: str) -> str | None:
    try:
        value = entry[attribute].value
    except LDAPException:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0]
    return None


def _bind_authenticate(
    settings: LdapProviderSettings, username: str, password: str
) -> LdapIdentity | None:
    # An empty password would trigger an unauthenticated anonymous bind that
    # LDAP servers accept — a silent auth bypass. Reject it outright.
    if not password:
        return None
    # StartTLS upgrades a plaintext link to TLS, so it is a no-op over an
    # ldaps:// URI whose socket is already SSL-wrapped — and a *silent* one
    # under ldap3's SYNC strategy (start_tls() returns False without raising).
    # Skip it there and warn, so an admin who enabled both isn't left
    # wondering why their StartTLS toggle does nothing; the connection stays
    # TLS-encrypted via the initial SSL wrap regardless.
    use_ssl = settings.server_uri.lower().startswith("ldaps://")
    apply_start_tls = settings.start_tls and not use_ssl
    if settings.start_tls and use_ssl:
        _logger.warning(
            "LDAP startTls ignored: server_uri is already ldaps:// (connection is already TLS-encrypted)"
        )
    server = _make_server(
        settings.server_uri,
        use_ssl=use_ssl,
        get_info=None,
    )
    search_conn = _make_connection(
        server,
        user=settings.bind_dn or None,
        password=settings.bind_password or None,
    )
    if apply_start_tls:
        _ = search_conn.start_tls()
    if not search_conn.bind():
        search_conn.unbind()
        return None
    try:
        search_filter = settings.user_filter.replace(
            "{username}", _escape_filter(username)
        )
        _ = search_conn.search(
            settings.user_search_base,
            search_filter,
            [settings.email_attribute],
        )
        if not search_conn.entries:
            return None
        entry = search_conn.entries[0]
        user_dn = entry.entry_dn
        email = _entry_email(entry, settings.email_attribute)
    finally:
        search_conn.unbind()

    # Re-bind as the located user to verify the supplied password.
    user_conn = _make_connection(server, user=user_dn, password=password)
    if apply_start_tls:
        _ = user_conn.start_tls()
    authenticated = user_conn.bind()
    user_conn.unbind()
    return LdapIdentity(username=username, email=email) if authenticated else None


async def ldap_authenticate(
    settings: LdapProviderSettings, username: str, password: str
) -> LdapIdentity | None:
    """Off-loop LDAP bind. Any protocol/transport failure means "not
    authenticated here" — the caller falls through to other providers."""
    try:
        return await asyncio.to_thread(_bind_authenticate, settings, username, password)
    except LDAPException as error:
        _logger.warning("LDAP authentication failed", error=str(error))
        return None
