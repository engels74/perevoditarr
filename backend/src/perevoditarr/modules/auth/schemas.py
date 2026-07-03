"""Auth API DTOs and internal provider-settings structs (P1-T2)."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

import msgspec

from perevoditarr.core.schemas import ApiRequest, ApiStruct

Username = Annotated[
    str, msgspec.Meta(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._@-]+$")
]
Password = Annotated[str, msgspec.Meta(min_length=10, max_length=256)]
BootstrapToken = Annotated[str, msgspec.Meta(min_length=1, max_length=64)]

type UserRole = Literal["admin", "viewer"]


type SetupPhase = Literal[
    "admin", "bazarr", "lingarr", "policy", "notifications", "finish", "done"
]


class SetupChecklist(ApiStruct):
    has_admin: bool
    bazarr_count: int
    lingarr_count: int
    notification_count: int


class SetupStatus(ApiStruct):
    required: bool
    bootstrap_required: bool
    completed: bool
    phase: SetupPhase
    checklist: SetupChecklist


class SetupRequest(ApiRequest):
    username: Username
    password: Password
    bootstrap_token: BootstrapToken
    email: str | None = None


class LoginRequest(ApiRequest):
    username: Username
    password: str


class UserRead(ApiStruct):
    id: UUID
    username: str
    email: str | None
    role: UserRole
    is_admin: bool
    is_active: bool
    created_at: datetime


class UserCreateRequest(ApiRequest):
    username: Username
    password: Password
    email: str | None = None
    role: UserRole = "viewer"


class UserRoleUpdate(ApiRequest):
    role: UserRole


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


class LdapSettingsWrite(ApiRequest):
    enabled: bool
    server_uri: Annotated[str, msgspec.Meta(min_length=1, max_length=512)]
    # Service account for the search bind; empty = anonymous bind.
    bind_dn: str = ""
    # Write-only (FR-A5); omit on update to keep the stored password.
    bind_password: str | None = None
    user_search_base: str = ""
    # {username} is substituted with the login name.
    user_filter: str = "(uid={username})"
    email_attribute: str = "mail"
    start_tls: bool = False
    auto_create_users: bool = True


class LdapSettingsRead(ApiStruct):
    enabled: bool
    server_uri: str
    bind_dn: str
    bind_password_set: bool
    user_search_base: str
    user_filter: str
    email_attribute: str
    start_tls: bool
    auto_create_users: bool


class LdapProviderSettings(msgspec.Struct, kw_only=True):
    enabled: bool
    server_uri: str
    bind_dn: str
    bind_password: str
    user_search_base: str
    user_filter: str
    email_attribute: str
    start_tls: bool
    auto_create_users: bool
