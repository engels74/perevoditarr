"""Auth API DTOs and internal provider-settings structs (P1-T2)."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

import msgspec

from perevoditarr.core.schemas import ApiRequest, ApiStruct

Username = Annotated[
    str, msgspec.Meta(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._@-]+$")
]
Password = Annotated[str, msgspec.Meta(min_length=10, max_length=256)]


class SetupStatus(ApiStruct):
    required: bool


class SetupRequest(ApiRequest):
    username: Username
    password: Password
    email: str | None = None


class LoginRequest(ApiRequest):
    username: Username
    password: str


class UserRead(ApiStruct):
    id: UUID
    username: str
    email: str | None
    is_admin: bool
    created_at: datetime


class ApiKeyCreateRequest(ApiRequest):
    name: Annotated[str, msgspec.Meta(min_length=1, max_length=64)]


class ApiKeyCreated(ApiStruct):
    id: UUID
    name: str
    prefix: str
    # The full key — returned exactly once, at creation (FR-A5).
    key: str


class ApiKeyRead(ApiStruct):
    id: UUID
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None


class OidcPublicInfo(ApiStruct):
    enabled: bool
    display_name: str


class LoginProviders(ApiStruct):
    builtin: bool
    oidc: OidcPublicInfo | None


class OidcSettingsWrite(ApiRequest):
    enabled: bool
    issuer: Annotated[str, msgspec.Meta(min_length=1, max_length=512)]
    client_id: Annotated[str, msgspec.Meta(min_length=1, max_length=256)]
    # Write-only: absent on read responses (FR-A5). May be omitted on update
    # to keep the previously stored secret.
    client_secret: str | None = None
    scopes: str = "openid profile email"
    display_name: str = "Single sign-on"
    auto_create_users: bool = True


class OidcSettingsRead(ApiStruct):
    enabled: bool
    issuer: str
    client_id: str
    client_secret_set: bool
    scopes: str
    display_name: str
    auto_create_users: bool


class ForwardAuthSettingsWrite(ApiRequest):
    enabled: bool
    user_header: str = "Remote-User"
    email_header: str = "Remote-Email"
    auto_create_users: bool = True


class ForwardAuthSettingsRead(ApiStruct):
    enabled: bool
    user_header: str
    email_header: str
    auto_create_users: bool
    trusted_proxies: list[str]


# --- internal, stored encrypted (never on the wire as-is) -------------------


class OidcProviderSettings(msgspec.Struct, kw_only=True):
    enabled: bool
    issuer: str
    client_id: str
    client_secret: str
    scopes: str
    display_name: str
    auto_create_users: bool


class ForwardAuthProviderSettings(msgspec.Struct, kw_only=True):
    enabled: bool
    user_header: str
    email_header: str
    auto_create_users: bool
