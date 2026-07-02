"""OIDC authorization-code + PKCE flow (FR-A2).

Authlib supplies the PKCE primitive; HTTP rides on the pooled registry
clients (Conventions §0 — one long-lived client per external system, no
transport retries). Identity comes from the issuer's userinfo endpoint over
TLS, resolved via discovery.
"""

import secrets
from typing import cast
from urllib.parse import urlencode

import msgspec
from authlib.oauth2.rfc7636 import (
    create_s256_code_challenge,  # pyright: ignore[reportUnknownVariableType]  # authlib ships no type information
)
from litestar.exceptions import NotAuthorizedException

from perevoditarr.core.errors import UpstreamError
from perevoditarr.core.http import HttpClientRegistry
from perevoditarr.core.security import SecretBox, SecretBoxError
from perevoditarr.modules.auth.schemas import OidcProviderSettings

OIDC_STATE_COOKIE = "pvd_oidc_state"
STATE_TTL_SECONDS = 600


class OidcDiscovery(msgspec.Struct, kw_only=True):
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str | None = None


class OidcTokenResponse(msgspec.Struct, kw_only=True):
    access_token: str
    token_type: str = "Bearer"
    id_token: str | None = None


class OidcUserInfo(msgspec.Struct, kw_only=True):
    sub: str
    email: str | None = None
    preferred_username: str | None = None
    name: str | None = None


class _StatePayload(msgspec.Struct, kw_only=True):
    state: str
    verifier: str


class OidcFlow:
    def __init__(
        self,
        *,
        settings: OidcProviderSettings,
        http: HttpClientRegistry,
        secret_box: SecretBox,
    ) -> None:
        self.settings: OidcProviderSettings = settings
        self.http: HttpClientRegistry = http
        self.secret_box: SecretBox = secret_box

    async def discovery(self) -> OidcDiscovery:
        issuer = self.settings.issuer.rstrip("/")
        client = self.http.get(issuer)
        try:
            response = await client.get(f"{issuer}/.well-known/openid-configuration")
            _ = response.raise_for_status()
        except Exception as error:
            raise UpstreamError(f"OIDC discovery failed for {issuer}") from error
        return msgspec.json.decode(response.content, type=OidcDiscovery)

    async def authorization_redirect(self, redirect_uri: str) -> tuple[str, str]:
        """Return (authorization URL, encrypted state-cookie value)."""
        discovery = await self.discovery()
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        # authlib's PKCE helper is untyped (returns Unknown); it already yields
        # a str, so the cast is a no-op that just restores the static type.
        challenge = cast("str", create_s256_code_challenge(verifier))
        params = urlencode(
            {
                "response_type": "code",
                "client_id": self.settings.client_id,
                "redirect_uri": redirect_uri,
                "scope": self.settings.scopes,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        cookie_value = self.secret_box.encrypt(
            msgspec.json.encode(_StatePayload(state=state, verifier=verifier))
        ).decode("ascii")
        return f"{discovery.authorization_endpoint}?{params}", cookie_value

    async def exchange_code(
        self, *, code: str, state: str, cookie_value: str, redirect_uri: str
    ) -> OidcUserInfo:
        try:
            payload = msgspec.json.decode(
                self.secret_box.decrypt(
                    cookie_value.encode("ascii"), ttl=STATE_TTL_SECONDS
                ),
                type=_StatePayload,
            )
        except (SecretBoxError, msgspec.DecodeError) as error:
            raise NotAuthorizedException("invalid or expired OIDC state") from error
        if not secrets.compare_digest(payload.state, state):
            raise NotAuthorizedException("OIDC state mismatch")

        discovery = await self.discovery()
        client = self.http.get(self.settings.issuer.rstrip("/"))
        token_response = await client.post(
            discovery.token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": self.settings.client_id,
                "client_secret": self.settings.client_secret,
                "code_verifier": payload.verifier,
            },
        )
        if token_response.status_code != 200:
            raise NotAuthorizedException("OIDC code exchange rejected by issuer")
        token = msgspec.json.decode(token_response.content, type=OidcTokenResponse)

        if discovery.userinfo_endpoint is None:
            raise UpstreamError("OIDC issuer advertises no userinfo endpoint")
        userinfo_response = await client.get(
            discovery.userinfo_endpoint,
            headers={"Authorization": f"Bearer {token.access_token}"},
        )
        if userinfo_response.status_code != 200:
            raise NotAuthorizedException("OIDC userinfo request rejected by issuer")
        return msgspec.json.decode(userinfo_response.content, type=OidcUserInfo)
