"""Auth module public interface (P1-T2).

Other modules import only from here (PRD §2.2).
"""

from perevoditarr.modules.auth.controllers import (
    AuthController,
    SetupController,
    UsersController,
    provide_auth_service,
    provide_provider_service,
)
from perevoditarr.modules.auth.models import ApiKey, AuthProviderConfig, User
from perevoditarr.modules.auth.security import (
    ApiKeyAwareCSRFMiddleware,
    AuthRuntime,
    SessionAuthenticator,
    SetupRequiredError,
    auth_runtime,
    build_jwt_auth,
    enforce_role,
    require_admin,
    setup_gate_middleware,
)

__all__ = [
    "ApiKey",
    "ApiKeyAwareCSRFMiddleware",
    "AuthController",
    "AuthProviderConfig",
    "AuthRuntime",
    "SessionAuthenticator",
    "SetupController",
    "SetupRequiredError",
    "User",
    "UsersController",
    "auth_runtime",
    "build_jwt_auth",
    "enforce_role",
    "provide_auth_service",
    "provide_provider_service",
    "require_admin",
    "setup_gate_middleware",
]
