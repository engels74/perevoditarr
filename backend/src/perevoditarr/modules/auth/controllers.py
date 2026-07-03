"""Auth & first-run setup controllers (P1-T2)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Annotated, cast
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from litestar import Controller, Request, Response, delete, get, patch, post, put
from litestar.datastructures import State
from litestar.exceptions import NotAuthorizedException
from litestar.params import Parameter
from litestar.response import Redirect
from litestar.security.jwt import Token
from litestar.status_codes import HTTP_200_OK
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.core.bootstrap import InvalidBootstrapTokenError
from perevoditarr.core.errors import DomainValidationError
from perevoditarr.core.http import HttpClientRegistry
from perevoditarr.core.logging import get_logger
from perevoditarr.modules.auth.ldap import ldap_authenticate
from perevoditarr.modules.auth.models import User
from perevoditarr.modules.auth.oidc import OIDC_STATE_COOKIE, OidcFlow
from perevoditarr.modules.auth.schemas import (
    ApiKeyCreated,
    ApiKeyCreateRequest,
    ApiKeyRead,
    ForwardAuthProviderSettings,
    ForwardAuthSettingsRead,
    ForwardAuthSettingsWrite,
    LdapProviderSettings,
    LdapSettingsRead,
    LdapSettingsWrite,
    LoginProviders,
    LoginRequest,
    OidcProviderSettings,
    OidcPublicInfo,
    OidcSettingsRead,
    OidcSettingsWrite,
    SetupChecklist,
    SetupPhase,
    SetupRequest,
    SetupStatus,
    UserCreateRequest,
    UserRead,
    UserRole,
    UserRoleUpdate,
)
from perevoditarr.modules.auth.security import (
    AuthRuntime,
    SessionAuthenticator,
    require_admin,
)
from perevoditarr.modules.auth.service import AuthService, ProviderConfigService

if TYPE_CHECKING:
    # Runtime imports of these sibling-module services would pull their package
    # __init__ chains (notifications -> dispatch -> instances) back through auth
    # during auth's own early import, creating a cycle. They are injected via
    # DI at runtime; the app registers them in signature_namespace so Litestar
    # resolves these forward references when it builds the handler signatures.
    from perevoditarr.modules.instances.service import InstancesService
    from perevoditarr.modules.notifications.service import NotificationsService

type UserRequest = Request[User, Token | str, State]
type SessionAuth = SessionAuthenticator

_OIDC_COOKIE_PATH = "/api/v1/auth/oidc"

_logger = get_logger()


def _user_read(user: User) -> UserRead:
    return UserRead(
        id=user.id,
        username=user.username,
        email=user.email,
        role=cast("UserRole", user.role),
        is_admin=user.is_admin,
        is_active=user.is_active,
        created_at=user.created_at,
    )


def _callback_uri(request: Request[object, object, State]) -> str:
    parts = urlsplit(str(request.url))
    return urlunsplit(
        (parts.scheme, parts.netloc, "/api/v1/auth/oidc/callback", "", "")
    )


async def _build_setup_status(
    *,
    auth_service: AuthService,
    auth_runtime: AuthRuntime,
    instances_service: InstancesService,
    notifications_service: NotificationsService,
) -> SetupStatus:
    """Derive the resume state from durable domain facts.

    `phase` is the first unsatisfied REQUIRED step (admin -> bazarr); the
    optional lingarr/policy/notifications steps never move it away from
    "finish" once admin + >=1 Bazarr exist. `done` only once completion is
    the durable, cached fact.
    """
    user_count = await auth_service.user_count()
    bazarr_count = len(await instances_service.list_bazarr())
    lingarr_count = len(await instances_service.list_lingarr())
    notification_count = len(await notifications_service.list_routes())
    completed = await auth_runtime.is_setup_completed()
    if completed:
        phase: SetupPhase = "done"
    elif user_count == 0:
        phase = "admin"
    elif bazarr_count == 0:
        phase = "bazarr"
    else:
        phase = "finish"
    return SetupStatus(
        required=not completed,
        bootstrap_required=user_count == 0,
        completed=completed,
        phase=phase,
        checklist=SetupChecklist(
            has_admin=user_count > 0,
            bazarr_count=bazarr_count,
            lingarr_count=lingarr_count,
            notification_count=notification_count,
        ),
    )


class SetupController(Controller):
    path: str = "/setup"
    tags: Sequence[str] | None = ("setup",)

    @get("/status", exclude_from_auth=True, operation_id="getSetupStatus")
    async def status(
        self,
        auth_service: AuthService,
        auth_runtime: AuthRuntime,
        instances_service: InstancesService,
        notifications_service: NotificationsService,
    ) -> SetupStatus:
        return await _build_setup_status(
            auth_service=auth_service,
            auth_runtime=auth_runtime,
            instances_service=instances_service,
            notifications_service=notifications_service,
        )

    @post(
        "/",
        exclude_from_auth=True,
        status_code=HTTP_200_OK,
        operation_id="completeSetup",
    )
    async def complete(
        self,
        data: SetupRequest,
        auth_service: AuthService,
        auth_runtime: AuthRuntime,
        session_auth: SessionAuth,
    ) -> Response[UserRead]:
        if not auth_runtime.bootstrap.validate(data.bootstrap_token):
            raise InvalidBootstrapTokenError(
                "bootstrap token is missing, incorrect, or expired"
            )
        user = await auth_service.create_initial_admin(
            username=data.username, password=data.password, email=data.email
        )
        auth_runtime.bootstrap.clear()
        return session_auth.login(
            identifier=str(user.id), response_body=_user_read(user)
        )

    @post("/finish", operation_id="finishSetup", guards=[require_admin])
    async def finish(
        self,
        auth_service: AuthService,
        auth_runtime: AuthRuntime,
        instances_service: InstancesService,
        notifications_service: NotificationsService,
    ) -> SetupStatus:
        user_count = await auth_service.user_count()
        bazarr_count = len(await instances_service.list_bazarr())
        if user_count == 0 or bazarr_count < 1:
            _logger.warning(
                "setup finish rejected: prerequisites unmet",
                user_count=user_count,
                bazarr_count=bazarr_count,
            )
            raise DomainValidationError(
                "complete the required steps first: create an admin and at least one Bazarr instance"
            )
        await auth_service.mark_setup_completed()
        auth_runtime.mark_setup_completed()
        # Mirror POST /setup: retire the startup bootstrap token on every
        # completion path (idempotent when unminted/already cleared).
        auth_runtime.bootstrap.clear()
        status = await _build_setup_status(
            auth_service=auth_service,
            auth_runtime=auth_runtime,
            instances_service=instances_service,
            notifications_service=notifications_service,
        )
        _logger.info(
            "setup completed",
            bazarr_count=status.checklist.bazarr_count,
            lingarr_count=status.checklist.lingarr_count,
            notification_count=status.checklist.notification_count,
        )
        return status


class AuthController(Controller):
    path: str = "/auth"
    tags: Sequence[str] | None = ("auth",)

    # --- sessions --------------------------------------------------------

    @post(
        "/login", exclude_from_auth=True, status_code=HTTP_200_OK, operation_id="login"
    )
    async def login(
        self,
        data: LoginRequest,
        auth_service: AuthService,
        auth_runtime: AuthRuntime,
        session_auth: SessionAuth,
    ) -> Response[UserRead]:
        user = await auth_service.authenticate(data.username, data.password)
        # LDAP is a fallback so local users still authenticate first (FR-A4).
        ldap = auth_runtime.ldap
        if user is None and ldap is not None and ldap.enabled:
            identity = await ldap_authenticate(ldap, data.username, data.password)
            if identity is not None:
                user = await auth_service.get_or_provision_external(
                    username=identity.username,
                    email=identity.email,
                    oidc_subject=None,
                    auto_create=ldap.auto_create_users,
                )
        if user is None:
            raise NotAuthorizedException("invalid credentials")
        return session_auth.login(
            identifier=str(user.id), response_body=_user_read(user)
        )

    @post(
        "/refresh",
        status_code=HTTP_200_OK,
        operation_id="refreshSession",
        opt={"viewer_write": True},
    )
    async def refresh(
        self, request: UserRequest, session_auth: SessionAuth
    ) -> Response[UserRead]:
        return session_auth.login(
            identifier=str(request.user.id), response_body=_user_read(request.user)
        )

    @post(
        "/logout",
        status_code=HTTP_200_OK,
        operation_id="logout",
        opt={"viewer_write": True},
    )
    async def logout(self, session_auth: SessionAuth) -> Response[None]:
        response = Response[None](None)
        response.delete_cookie(session_auth.cookie_key)
        return response

    @get("/me", operation_id="getCurrentUser")
    async def me(self, request: UserRequest) -> UserRead:
        return _user_read(request.user)

    @get("/providers", exclude_from_auth=True, operation_id="getLoginProviders")
    async def providers(self, auth_runtime: AuthRuntime) -> LoginProviders:
        oidc = auth_runtime.oidc
        return LoginProviders(
            builtin=True,
            oidc=OidcPublicInfo(enabled=True, display_name=oidc.display_name)
            if oidc is not None and oidc.enabled
            else None,
        )

    # --- API keys --------------------------------------------------------

    @get("/api-keys", operation_id="listApiKeys")
    async def list_api_keys(
        self, request: UserRequest, auth_service: AuthService
    ) -> list[ApiKeyRead]:
        keys = await auth_service.list_api_keys(request.user)
        return [
            ApiKeyRead(
                id=key.id,
                name=key.name,
                prefix=key.prefix,
                created_at=key.created_at,
                last_used_at=key.last_used_at,
            )
            for key in keys
        ]

    @post("/api-keys", operation_id="createApiKey")
    async def create_api_key(
        self,
        request: UserRequest,
        data: ApiKeyCreateRequest,
        auth_service: AuthService,
    ) -> ApiKeyCreated:
        api_key, raw = await auth_service.create_api_key(request.user, data.name)
        return ApiKeyCreated(
            id=api_key.id, name=api_key.name, prefix=api_key.prefix, key=raw
        )

    @delete("/api-keys/{key_id:uuid}", operation_id="deleteApiKey")
    async def delete_api_key(
        self, request: UserRequest, key_id: UUID, auth_service: AuthService
    ) -> None:
        await auth_service.delete_api_key(request.user, key_id)

    # --- OIDC flow -------------------------------------------------------

    @get("/oidc/login", exclude_from_auth=True, operation_id="oidcLogin")
    async def oidc_login(
        self,
        request: Request[object, object, State],
        auth_runtime: AuthRuntime,
        http: HttpClientRegistry,
    ) -> Redirect:
        oidc = auth_runtime.oidc
        if oidc is None or not oidc.enabled:
            raise DomainValidationError("OIDC is not enabled")
        flow = OidcFlow(settings=oidc, http=http, secret_box=auth_runtime.secret_box)
        url, cookie_value = await flow.authorization_redirect(_callback_uri(request))
        response = Redirect(url, status_code=302)
        response.set_cookie(
            OIDC_STATE_COOKIE,
            cookie_value,
            max_age=600,
            httponly=True,
            samesite="lax",
            path=_OIDC_COOKIE_PATH,
        )
        return response

    @get("/oidc/callback", exclude_from_auth=True, operation_id="oidcCallback")
    async def oidc_callback(
        self,
        request: Request[object, object, State],
        auth_runtime: AuthRuntime,
        http: HttpClientRegistry,
        auth_service: AuthService,
        session_auth: SessionAuth,
        code: str,
        oidc_state: Annotated[str, Parameter(query="state")],
    ) -> Redirect:
        oidc = auth_runtime.oidc
        if oidc is None or not oidc.enabled:
            raise DomainValidationError("OIDC is not enabled")
        cookie_value = request.cookies.get(OIDC_STATE_COOKIE)
        if cookie_value is None:
            raise NotAuthorizedException("missing OIDC state cookie")
        flow = OidcFlow(settings=oidc, http=http, secret_box=auth_runtime.secret_box)
        info = await flow.exchange_code(
            code=code,
            state=oidc_state,
            cookie_value=cookie_value,
            redirect_uri=_callback_uri(request),
        )
        username = info.preferred_username or info.email or f"oidc-{info.sub[:12]}"
        user = await auth_service.get_or_provision_external(
            username=username,
            email=info.email,
            oidc_subject=info.sub,
            auto_create=oidc.auto_create_users,
        )
        if user is None:
            raise NotAuthorizedException("user is not permitted to sign in")
        response = Redirect("/", status_code=302)
        response.set_cookie(
            session_auth.cookie_key,
            session_auth.session_cookie_value(str(user.id)),
            httponly=True,
            samesite="lax",
            secure=session_auth.cookie_secure,
        )
        response.delete_cookie(OIDC_STATE_COOKIE, path=_OIDC_COOKIE_PATH)
        return response

    # --- provider administration ----------------------------------------

    @get(
        "/providers/oidc",
        guards=[require_admin],
        operation_id="getOidcProviderSettings",
    )
    async def read_oidc_settings(
        self, provider_service: ProviderConfigService
    ) -> OidcSettingsRead | None:
        stored = await provider_service.load_oidc()
        if stored is None:
            return None
        return OidcSettingsRead(
            enabled=stored.enabled,
            issuer=stored.issuer,
            client_id=stored.client_id,
            client_secret_set=bool(stored.client_secret),
            scopes=stored.scopes,
            display_name=stored.display_name,
            auto_create_users=stored.auto_create_users,
        )

    @put(
        "/providers/oidc",
        guards=[require_admin],
        operation_id="putOidcProviderSettings",
    )
    async def write_oidc_settings(
        self,
        data: OidcSettingsWrite,
        provider_service: ProviderConfigService,
        auth_runtime: AuthRuntime,
    ) -> OidcSettingsRead:
        existing = await provider_service.load_oidc()
        client_secret = data.client_secret
        if client_secret is None and existing is not None:
            client_secret = existing.client_secret
        if not client_secret:
            raise DomainValidationError("clientSecret is required")
        stored = OidcProviderSettings(
            enabled=data.enabled,
            issuer=data.issuer,
            client_id=data.client_id,
            client_secret=client_secret,
            scopes=data.scopes,
            display_name=data.display_name,
            auto_create_users=data.auto_create_users,
        )
        await provider_service.store_oidc(stored)
        auth_runtime.oidc = stored
        return OidcSettingsRead(
            enabled=stored.enabled,
            issuer=stored.issuer,
            client_id=stored.client_id,
            client_secret_set=True,
            scopes=stored.scopes,
            display_name=stored.display_name,
            auto_create_users=stored.auto_create_users,
        )

    @get(
        "/providers/forward-auth",
        guards=[require_admin],
        operation_id="getForwardAuthSettings",
    )
    async def read_forward_auth_settings(
        self, provider_service: ProviderConfigService, auth_runtime: AuthRuntime
    ) -> ForwardAuthSettingsRead | None:
        stored = await provider_service.load_forward_auth()
        if stored is None:
            return None
        return ForwardAuthSettingsRead(
            enabled=stored.enabled,
            user_header=stored.user_header,
            email_header=stored.email_header,
            auto_create_users=stored.auto_create_users,
            trusted_proxies=list(auth_runtime.settings.trusted_proxies),
        )

    @put(
        "/providers/forward-auth",
        guards=[require_admin],
        operation_id="putForwardAuthSettings",
    )
    async def write_forward_auth_settings(
        self,
        data: ForwardAuthSettingsWrite,
        provider_service: ProviderConfigService,
        auth_runtime: AuthRuntime,
    ) -> ForwardAuthSettingsRead:
        if data.enabled and not auth_runtime.trusted_networks:
            # Hard-fail (P1-T2): forward-auth without trusted proxies is an
            # authentication bypass waiting to happen.
            raise DomainValidationError(
                "PEREVODITARR_TRUSTED_PROXIES must be configured before "
                + "enabling forward-auth"
            )
        stored = ForwardAuthProviderSettings(
            enabled=data.enabled,
            user_header=data.user_header,
            email_header=data.email_header,
            auto_create_users=data.auto_create_users,
        )
        await provider_service.store_forward_auth(stored)
        auth_runtime.forward_auth = stored
        return ForwardAuthSettingsRead(
            enabled=stored.enabled,
            user_header=stored.user_header,
            email_header=stored.email_header,
            auto_create_users=stored.auto_create_users,
            trusted_proxies=list(auth_runtime.settings.trusted_proxies),
        )

    @get(
        "/providers/ldap",
        guards=[require_admin],
        operation_id="getLdapProviderSettings",
    )
    async def read_ldap_settings(
        self, provider_service: ProviderConfigService
    ) -> LdapSettingsRead | None:
        stored = await provider_service.load_ldap()
        return _ldap_read(stored) if stored is not None else None

    @put(
        "/providers/ldap",
        guards=[require_admin],
        operation_id="putLdapProviderSettings",
    )
    async def write_ldap_settings(
        self,
        data: LdapSettingsWrite,
        provider_service: ProviderConfigService,
        auth_runtime: AuthRuntime,
    ) -> LdapSettingsRead:
        existing = await provider_service.load_ldap()
        bind_password = data.bind_password
        if bind_password is None and existing is not None:
            bind_password = existing.bind_password
        stored = LdapProviderSettings(
            enabled=data.enabled,
            server_uri=data.server_uri,
            bind_dn=data.bind_dn,
            # Empty is legitimate: an anonymous search bind (FR-A4).
            bind_password=bind_password or "",
            user_search_base=data.user_search_base,
            user_filter=data.user_filter,
            email_attribute=data.email_attribute,
            start_tls=data.start_tls,
            auto_create_users=data.auto_create_users,
        )
        await provider_service.store_ldap(stored)
        auth_runtime.ldap = stored
        return _ldap_read(stored)


def _ldap_read(stored: LdapProviderSettings) -> LdapSettingsRead:
    return LdapSettingsRead(
        enabled=stored.enabled,
        server_uri=stored.server_uri,
        bind_dn=stored.bind_dn,
        bind_password_set=bool(stored.bind_password),
        user_search_base=stored.user_search_base,
        user_filter=stored.user_filter,
        email_attribute=stored.email_attribute,
        start_tls=stored.start_tls,
        auto_create_users=stored.auto_create_users,
    )


class UsersController(Controller):
    """User management (admin-only, FR-A6). require_admin gates every handler,
    including the list, so viewers cannot enumerate accounts."""

    path: str = "/auth/users"
    tags: Sequence[str] | None = ("auth",)

    @get("/", guards=[require_admin], operation_id="listUsers")
    async def list_users(self, auth_service: AuthService) -> list[UserRead]:
        return [_user_read(user) for user in await auth_service.list_users()]

    @post("/", guards=[require_admin], operation_id="createUser")
    async def create_user(
        self, data: UserCreateRequest, auth_service: AuthService
    ) -> UserRead:
        user = await auth_service.create_user(
            username=data.username,
            password=data.password,
            email=data.email,
            role=data.role,
        )
        return _user_read(user)

    @patch("/{user_id:uuid}/role", guards=[require_admin], operation_id="setUserRole")
    async def set_role(
        self, user_id: UUID, data: UserRoleUpdate, auth_service: AuthService
    ) -> UserRead:
        return _user_read(await auth_service.set_role(user_id, data.role))

    @delete("/{user_id:uuid}", guards=[require_admin], operation_id="deleteUser")
    async def delete_user(
        self, user_id: UUID, request: UserRequest, auth_service: AuthService
    ) -> None:
        await auth_service.delete_user(user_id, actor_id=request.user.id)


async def provide_auth_service(db_session: AsyncSession) -> AuthService:
    return AuthService(db_session)


async def provide_provider_service(
    db_session: AsyncSession, auth_runtime: AuthRuntime
) -> ProviderConfigService:
    return ProviderConfigService(db_session, auth_runtime.secret_box)
