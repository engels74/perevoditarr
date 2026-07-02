"""Auth wiring: JWT cookie sessions, API-key header, forward-auth, setup gate.

All three credential paths resolve through one middleware so every endpoint
shares a single authorization model (FR-API3).
"""

import ipaddress
from typing import Any, ClassVar
from uuid import UUID

from advanced_alchemy.extensions.litestar import SQLAlchemyAsyncConfig
from litestar import Response
from litestar.connection import ASGIConnection
from litestar.datastructures import State
from litestar.exceptions import NotAuthorizedException, PermissionDeniedException
from litestar.handlers.base import BaseRouteHandler
from litestar.middleware.authentication import AuthenticationResult
from litestar.middleware.csrf import CSRFMiddleware
from litestar.security.jwt import (
    JWTCookieAuth,
    JWTCookieAuthenticationMiddleware,
    Token,
)
from litestar.types import ASGIApp, Receive, Scope, Send

from perevoditarr.core.errors import PerevoditarrError
from perevoditarr.core.security import (
    SecretBox,
    jwt_signing_secret,
    resolve_secret_key,
)
from perevoditarr.core.settings import AppSettings
from perevoditarr.modules.auth.models import User
from perevoditarr.modules.auth.schemas import (
    ForwardAuthProviderSettings,
    OidcProviderSettings,
)
from perevoditarr.modules.auth.service import AuthService, ProviderConfigService

API_KEY_HEADER = "X-API-KEY"

type _AnyConnection = ASGIConnection[Any, Any, Any, Any]
type _IpNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


class SetupRequiredError(PerevoditarrError):
    status_code: ClassVar[int] = 403
    code: ClassVar[str] = "setup-required"
    title: ClassVar[str] = "First-run setup required"


class AuthRuntime:
    """Auth state the middleware needs outside DI; lives on app.state."""

    def __init__(
        self,
        *,
        settings: AppSettings,
        secret_box: SecretBox,
        alchemy_config: SQLAlchemyAsyncConfig,
    ) -> None:
        self.settings: AppSettings = settings
        self.secret_box: SecretBox = secret_box
        self.alchemy: SQLAlchemyAsyncConfig = alchemy_config
        self.trusted_networks: tuple[_IpNetwork, ...] = tuple(
            ipaddress.ip_network(cidr, strict=False)
            for cidr in settings.trusted_proxies
        )
        self.forward_auth: ForwardAuthProviderSettings | None = None
        self.oidc: OidcProviderSettings | None = None
        self._setup_completed: bool = False

    async def refresh_providers(self) -> None:
        async with self.alchemy.get_session() as session:
            service = ProviderConfigService(session, self.secret_box)
            self.oidc = await service.load_oidc()
            self.forward_auth = await service.load_forward_auth()

    async def is_setup_completed(self) -> bool:
        if self._setup_completed:
            return True
        async with self.alchemy.get_session() as session:
            if await AuthService(session).user_count() > 0:
                self._setup_completed = True
        return self._setup_completed

    def mark_setup_completed(self) -> None:
        self._setup_completed = True

    def client_is_trusted_proxy(self, client_host: str | None) -> bool:
        if not self.trusted_networks:
            # Forward-auth without configured trusted proxies must never
            # authenticate anyone (P1-T2 hard-fail requirement).
            return False
        if client_host is None:
            return False
        try:
            address = ipaddress.ip_address(client_host)
        except ValueError:
            return False
        return any(address in network for network in self.trusted_networks)


def auth_runtime(state: State) -> AuthRuntime:
    runtime: object = state.get("auth_runtime")
    if not isinstance(runtime, AuthRuntime):
        raise RuntimeError("auth runtime is not configured on app.state")
    return runtime


class PerevoditarrAuthMiddleware(JWTCookieAuthenticationMiddleware):
    async def authenticate_request(
        self, connection: _AnyConnection
    ) -> AuthenticationResult:
        runtime = auth_runtime(connection.app.state)

        raw_key = connection.headers.get(API_KEY_HEADER)
        if raw_key:
            session = runtime.alchemy.provide_session(
                connection.app.state, connection.scope
            )
            user = await AuthService(session).resolve_api_key(raw_key)
            if user is None:
                raise NotAuthorizedException("invalid API key")
            return AuthenticationResult(user=user, auth="api-key")

        client = connection.scope.get("client")
        forward = runtime.forward_auth
        if (
            forward is not None
            and forward.enabled
            and runtime.client_is_trusted_proxy(client[0] if client else None)
        ):
            username = connection.headers.get(forward.user_header)
            if username:
                session = runtime.alchemy.provide_session(
                    connection.app.state, connection.scope
                )
                user = await AuthService(session).get_or_provision_external(
                    username=username,
                    email=connection.headers.get(forward.email_header),
                    oidc_subject=None,
                    auto_create=forward.auto_create_users,
                )
                if user is None:
                    raise NotAuthorizedException("unknown forward-auth user")
                return AuthenticationResult(user=user, auth="forward-auth")

        return await super().authenticate_request(connection)


async def _retrieve_user_handler(
    token: Token, connection: _AnyConnection
) -> User | None:
    runtime = auth_runtime(connection.app.state)
    try:
        user_id = UUID(token.sub)
    except ValueError:
        return None
    session = runtime.alchemy.provide_session(connection.app.state, connection.scope)
    return await AuthService(session).get_active_user(user_id)


def build_jwt_auth(settings: AppSettings) -> JWTCookieAuth[User, Token]:
    return JWTCookieAuth[User, Token](
        retrieve_user_handler=_retrieve_user_handler,
        token_secret=jwt_signing_secret(resolve_secret_key(settings)),
        authentication_middleware_class=PerevoditarrAuthMiddleware,
        # API/auth exclusions are declared per-handler (and on the static SPA
        # router) via the exclude_from_auth opt.
        exclude=["^/schema"],
        samesite="lax",
    )


class SessionAuthenticator:
    """Plain wrapper handlers can depend on.

    JWTCookieAuth itself is a dataclass whose annotations only resolve under
    TYPE_CHECKING, which breaks Litestar's msgspec signature modelling when
    used directly as a dependency type.
    """

    def __init__(self, jwt_auth: JWTCookieAuth[User, Token]) -> None:
        self._jwt_auth: JWTCookieAuth[User, Token] = jwt_auth

    @property
    def cookie_key(self) -> str:
        return self._jwt_auth.key

    def login[T](self, *, identifier: str, response_body: T) -> Response[T]:
        return self._jwt_auth.login(
            identifier=identifier,
            response_body=response_body,
            response_status_code=200,
        )

    def session_cookie_value(self, identifier: str) -> str:
        token = self._jwt_auth.create_token(identifier=identifier)
        return self._jwt_auth.format_auth_header(token)

    @property
    def cookie_secure(self) -> bool:
        return bool(self._jwt_auth.secure)


_SETUP_ALLOWED_PREFIXES = ("/api/v1/setup", "/api/v1/health")


def setup_gate_middleware(app: ASGIApp) -> ASGIApp:
    """While no user exists, the API exposes only /api/v1/setup (FR-A1)."""

    async def middleware(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope["path"]
            if path.startswith("/api/") and not path.startswith(
                _SETUP_ALLOWED_PREFIXES
            ):
                runtime = auth_runtime(scope["app"].state)
                if not await runtime.is_setup_completed():
                    raise SetupRequiredError(
                        "no user exists yet: complete /api/v1/setup first"
                    )
        await app(scope, receive, send)

    return middleware


class ApiKeyAwareCSRFMiddleware(CSRFMiddleware):
    """CSRF protects cookie sessions; API-key requests carry no cookies and skip it."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            if headers.get(API_KEY_HEADER.lower().encode("latin-1")):
                await self.app(scope, receive, send)
                return
        await super().__call__(scope, receive, send)


def require_admin(connection: _AnyConnection, _: BaseRouteHandler) -> None:
    user: object = connection.user
    if not isinstance(user, User) or not user.is_admin:
        raise PermissionDeniedException("administrator access required")
