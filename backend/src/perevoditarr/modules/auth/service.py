"""Auth domain services (P1-T2)."""

import asyncio
import hashlib
import secrets
from datetime import UTC, datetime
from uuid import UUID

import msgspec
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from perevoditarr.core.errors import (
    ConflictError,
    DomainValidationError,
    NotFoundError,
)
from perevoditarr.core.logging import get_logger
from perevoditarr.core.security import SecretBox
from perevoditarr.modules.auth.models import ApiKey, AuthProviderConfig, User
from perevoditarr.modules.auth.schemas import (
    ForwardAuthProviderSettings,
    LdapProviderSettings,
    OidcProviderSettings,
    Password,
)

_logger = get_logger()

_hasher = PasswordHasher()  # argon2id with library defaults

API_KEY_PREFIX = "pvd_"
_API_KEY_PREFIX_LEN = 12

OIDC_PROVIDER = "oidc"
FORWARD_AUTH_PROVIDER = "forward_auth"
LDAP_PROVIDER = "ldap"


def _hash_api_key(raw: str) -> str:
    # API keys are high-entropy random tokens: an unsalted SHA-256 digest is
    # the standard, constant-time-lookup-friendly storage form.
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _validate_password(password: str) -> None:
    """Reject empty, whitespace-only, or out-of-policy passwords before hashing.

    Shared by every credential-creation path so the admin CLI enforces the same
    rule as the HTTP /setup DTO (auth.schemas.Password). Without it, argon2 will
    happily hash "" or "   ", persisting an admin with a trivial credential.
    """
    if not password.strip():
        raise DomainValidationError("password must not be empty or whitespace-only")
    try:
        # msgspec.convert against an Annotated alias is typed as Any by the stub.
        _ = msgspec.convert(password, type=Password)  # pyright: ignore[reportAny]
    except msgspec.ValidationError as error:
        raise DomainValidationError(f"password rejected: {error}") from error


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session: AsyncSession = session

    # --- users ---------------------------------------------------------

    async def user_count(self) -> int:
        result = await self.session.scalar(select(func.count(User.id)))
        return result or 0

    async def create_initial_admin(
        self, *, username: str, password: str, email: str | None
    ) -> User:
        _validate_password(password)
        if await self.user_count() > 0:
            raise ConflictError("setup already completed: a user exists")
        password_hash = await asyncio.to_thread(_hasher.hash, password)
        user = User(
            username=username,
            email=email,
            password_hash=password_hash,
            role="admin",
        )
        self.session.add(user)
        await self.session.commit()
        return user

    async def create_user(
        self,
        *,
        username: str,
        password: str,
        email: str | None = None,
        role: str = "admin",
    ) -> User:
        """Create a user (admin CLI, P4-T3). Unlike create_initial_admin this has
        no first-run guard, but it still rejects a duplicate username."""
        _validate_password(password)
        existing = (
            await self.session.scalars(select(User.id).where(User.username == username))
        ).first()
        if existing is not None:
            raise ConflictError(f"a user named {username!r} already exists")
        password_hash = await asyncio.to_thread(_hasher.hash, password)
        user = User(
            username=username,
            email=email,
            password_hash=password_hash,
            role=role,
        )
        self.session.add(user)
        await self.session.commit()
        return user

    async def authenticate(self, username: str, password: str) -> User | None:
        user = (
            await self.session.scalars(select(User).where(User.username == username))
        ).one_or_none()
        if user is None or user.password_hash is None or not user.is_active:
            return None
        try:
            _ = await asyncio.to_thread(_hasher.verify, user.password_hash, password)
        except VerifyMismatchError, VerificationError:
            return None
        if _hasher.check_needs_rehash(user.password_hash):
            user.password_hash = await asyncio.to_thread(_hasher.hash, password)
            await self.session.commit()
        return user

    async def get_active_user(self, user_id: UUID) -> User | None:
        user = await self.session.get(User, user_id)
        return user if user is not None and user.is_active else None

    async def get_or_provision_external(
        self,
        *,
        username: str,
        email: str | None,
        oidc_subject: str | None,
        auto_create: bool,
    ) -> User | None:
        """Resolve an externally-authenticated identity to a local user.

        Match order: OIDC subject (stable), then email (link), then username
        (forward-auth). Creates the user when auto_create allows it.
        """
        if oidc_subject is not None:
            user = (
                await self.session.scalars(
                    select(User).where(User.oidc_subject == oidc_subject)
                )
            ).one_or_none()
            if user is not None:
                return user if user.is_active else None
        if email is not None:
            user = (
                await self.session.scalars(select(User).where(User.email == email))
            ).one_or_none()
            if user is not None:
                if not user.is_active:
                    return None
                if oidc_subject is not None and user.oidc_subject is None:
                    user.oidc_subject = oidc_subject
                    await self.session.commit()
                return user
        user = (
            await self.session.scalars(select(User).where(User.username == username))
        ).one_or_none()
        if user is not None:
            return user if user.is_active else None
        if not auto_create:
            return None
        user = User(
            username=username,
            email=email,
            password_hash=None,
            oidc_subject=oidc_subject,
            # First externally-provisioned user bootstraps as admin; later ones
            # default to viewer, safe-by-default (ADR-0008).
            role="admin" if await self.user_count() == 0 else "viewer",
        )
        self.session.add(user)
        await self.session.commit()
        return user

    # --- user management (admin, FR-A6) ---------------------------------

    async def list_users(self) -> list[User]:
        return list(await self.session.scalars(select(User).order_by(User.created_at)))

    async def set_role(self, user_id: UUID, role: str) -> User:
        # Guard at the service layer so this domain invariant does not depend on
        # every caller pre-validating: the User.role column is a plain String(16)
        # with no Enum/CheckConstraint, so a bad value would persist silently.
        # Mirrors _validate_password's "reject bad input before persisting" idiom.
        if role not in ("admin", "viewer"):
            raise DomainValidationError("role must be 'admin' or 'viewer'")
        user = await self.session.get(User, user_id)
        if user is None:
            raise NotFoundError("user not found")
        if user.role == "admin" and role != "admin" and await self._admin_count() <= 1:
            raise ConflictError("cannot demote the last remaining admin")
        user.role = role
        await self.session.commit()
        return user

    async def delete_user(self, user_id: UUID, *, actor_id: UUID | None = None) -> None:
        user = await self.session.get(User, user_id)
        if user is None:
            raise NotFoundError("user not found")
        if actor_id is not None and user.id == actor_id:
            raise ConflictError("cannot delete your own account")
        if user.role == "admin" and await self._admin_count() <= 1:
            raise ConflictError("cannot delete the last remaining admin")
        await self.session.delete(user)
        await self.session.commit()

    async def _admin_count(self) -> int:
        result = await self.session.scalar(
            select(func.count(User.id)).where(User.role == "admin")
        )
        return result or 0

    # --- API keys --------------------------------------------------------

    async def create_api_key(self, user: User, name: str) -> tuple[ApiKey, str]:
        raw = API_KEY_PREFIX + secrets.token_urlsafe(32)
        api_key = ApiKey(
            user_id=user.id,
            name=name,
            prefix=raw[:_API_KEY_PREFIX_LEN],
            key_hash=_hash_api_key(raw),
        )
        self.session.add(api_key)
        await self.session.commit()
        return api_key, raw

    async def list_api_keys(self, user: User) -> list[ApiKey]:
        return list(
            await self.session.scalars(
                select(ApiKey)
                .where(ApiKey.user_id == user.id)
                .order_by(ApiKey.created_at)
            )
        )

    async def delete_api_key(self, user: User, api_key_id: UUID) -> None:
        api_key = await self.session.get(ApiKey, api_key_id)
        if api_key is None or api_key.user_id != user.id:
            raise NotFoundError("API key not found")
        await self.session.delete(api_key)
        await self.session.commit()

    async def resolve_api_key(self, raw: str) -> User | None:
        api_key = (
            await self.session.scalars(
                select(ApiKey)
                .where(ApiKey.key_hash == _hash_api_key(raw))
                .options(joinedload(ApiKey.user))
            )
        ).one_or_none()
        if api_key is None or not api_key.user.is_active:
            return None
        # Detach the fully-loaded user before the cosmetic commit below. A
        # rollback expires every instance still attached to the shared request
        # session, and ApiKey.user is lazy="raise", so re-reading it (or any
        # column of an expired user) after a rollback would raise. A detached
        # instance keeps its already-loaded columns, so the returned user stays
        # usable by the downstream guards/handlers regardless of the outcome.
        user = api_key.user
        self.session.expunge(user)
        api_key.last_used_at = datetime.now(UTC)
        try:
            await self.session.commit()
        except SQLAlchemyError as error:
            # last_used_at is a cosmetic timestamp; a transient write failure
            # must not reject an otherwise-valid key. Roll back so the shared
            # request session is left usable for the downstream handler.
            await self.session.rollback()
            _logger.warning("api key last_used_at update failed", error=str(error))
        return user


class ProviderConfigService:
    def __init__(self, session: AsyncSession, secret_box: SecretBox) -> None:
        self.session: AsyncSession = session
        self.secret_box: SecretBox = secret_box

    async def _row(self, provider_type: str) -> AuthProviderConfig | None:
        return (
            await self.session.scalars(
                select(AuthProviderConfig).where(
                    AuthProviderConfig.provider_type == provider_type
                )
            )
        ).one_or_none()

    async def load_oidc(self) -> OidcProviderSettings | None:
        row = await self._row(OIDC_PROVIDER)
        if row is None or row.settings_encrypted is None:
            return None
        return msgspec.json.decode(
            self.secret_box.decrypt(row.settings_encrypted), type=OidcProviderSettings
        )

    async def store_oidc(self, settings: OidcProviderSettings) -> None:
        await self._store(
            OIDC_PROVIDER, msgspec.json.encode(settings), settings.enabled
        )

    async def load_forward_auth(self) -> ForwardAuthProviderSettings | None:
        row = await self._row(FORWARD_AUTH_PROVIDER)
        if row is None or row.settings_encrypted is None:
            return None
        return msgspec.json.decode(
            self.secret_box.decrypt(row.settings_encrypted),
            type=ForwardAuthProviderSettings,
        )

    async def store_forward_auth(self, settings: ForwardAuthProviderSettings) -> None:
        await self._store(
            FORWARD_AUTH_PROVIDER, msgspec.json.encode(settings), settings.enabled
        )

    async def load_ldap(self) -> LdapProviderSettings | None:
        row = await self._row(LDAP_PROVIDER)
        if row is None or row.settings_encrypted is None:
            return None
        return msgspec.json.decode(
            self.secret_box.decrypt(row.settings_encrypted),
            type=LdapProviderSettings,
        )

    async def store_ldap(self, settings: LdapProviderSettings) -> None:
        await self._store(
            LDAP_PROVIDER, msgspec.json.encode(settings), settings.enabled
        )

    async def _store(self, provider_type: str, payload: bytes, enabled: bool) -> None:
        row = await self._row(provider_type)
        if row is None:
            row = AuthProviderConfig(provider_type=provider_type)
            self.session.add(row)
        row.enabled = enabled
        row.settings_encrypted = self.secret_box.encrypt(payload)
        await self.session.commit()
