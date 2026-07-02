"""Instances domain service (P1-T4): CRUD, credential encryption, snapshots.

CRUD rides Advanced Alchemy async repositories; anything richer stays 2.0
select() style.
"""

from uuid import UUID

import msgspec
from advanced_alchemy.exceptions import NotFoundError as AANotFoundError
from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from msgspec import UNSET
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.core.errors import ConflictError, NotFoundError
from perevoditarr.core.security import SecretBox
from perevoditarr.modules.instances.models import BazarrInstance, LingarrInstance
from perevoditarr.modules.instances.schemas import (
    BazarrCapabilities,
    BazarrInstanceCreate,
    BazarrInstanceRead,
    BazarrInstanceUpdate,
    InstanceHealth,
    LingarrInstanceCreate,
    LingarrInstanceRead,
    LingarrInstanceUpdate,
)


def _decode_json_column[T](raw: dict[str, object] | None, kind: type[T]) -> T | None:
    if raw is None:
        return None
    try:
        return msgspec.convert(raw, type=kind)
    except msgspec.ValidationError:
        # A snapshot written by a newer/older build is cosmetic data — never
        # let it break instance listing.
        return None


def _encode_json_column(value: msgspec.Struct) -> dict[str, object]:
    return msgspec.json.decode(msgspec.json.encode(value), type=dict[str, object])


def bazarr_read(instance: BazarrInstance) -> BazarrInstanceRead:
    return BazarrInstanceRead(
        id=instance.id,
        name=instance.name,
        url=instance.url,
        enabled=instance.enabled,
        version=instance.version,
        lingarr_instance_id=instance.lingarr_instance_id,
        capabilities=_decode_json_column(instance.capabilities, BazarrCapabilities),
        health=_decode_json_column(instance.health_snapshot, InstanceHealth),
        created_at=instance.created_at,
    )


def lingarr_read(instance: LingarrInstance) -> LingarrInstanceRead:
    return LingarrInstanceRead(
        id=instance.id,
        name=instance.name,
        url=instance.url,
        enabled=instance.enabled,
        version=instance.version,
        has_api_key=instance.api_key_encrypted is not None,
        health=_decode_json_column(instance.health_snapshot, InstanceHealth),
        created_at=instance.created_at,
    )


class BazarrInstanceRepository(SQLAlchemyAsyncRepository[BazarrInstance]):
    model_type: type[BazarrInstance] = BazarrInstance


class LingarrInstanceRepository(SQLAlchemyAsyncRepository[LingarrInstance]):
    model_type: type[LingarrInstance] = LingarrInstance


class InstancesService:
    def __init__(self, session: AsyncSession, secret_box: SecretBox) -> None:
        self.session: AsyncSession = session
        self.secret_box: SecretBox = secret_box
        self.bazarr_repo: BazarrInstanceRepository = BazarrInstanceRepository(
            session=session
        )
        self.lingarr_repo: LingarrInstanceRepository = LingarrInstanceRepository(
            session=session
        )

    # --- Bazarr ----------------------------------------------------------

    async def list_bazarr(self) -> list[BazarrInstance]:
        return list(await self.bazarr_repo.list(order_by=[("name", False)]))

    async def get_bazarr(self, instance_id: UUID) -> BazarrInstance:
        try:
            return await self.bazarr_repo.get(instance_id)
        except AANotFoundError as error:
            raise NotFoundError(f"Bazarr instance {instance_id} not found") from error

    def bazarr_api_key(self, instance: BazarrInstance) -> str:
        return self.secret_box.decrypt_text(instance.api_key_encrypted)

    async def create_bazarr(
        self,
        data: BazarrInstanceCreate,
        *,
        version: str | None,
        capabilities: BazarrCapabilities | None,
    ) -> BazarrInstance:
        await self._ensure_unique_name(BazarrInstance, data.name)
        instance = BazarrInstance(
            name=data.name,
            url=data.url.rstrip("/"),
            api_key_encrypted=self.secret_box.encrypt_text(data.api_key),
            enabled=data.enabled,
            version=version,
            capabilities=_encode_json_column(capabilities) if capabilities else None,
        )
        self.session.add(instance)
        await self.session.commit()
        return instance

    async def update_bazarr(
        self, instance_id: UUID, data: BazarrInstanceUpdate
    ) -> BazarrInstance:
        instance = await self.get_bazarr(instance_id)
        if data.name is not UNSET and data.name != instance.name:
            await self._ensure_unique_name(BazarrInstance, data.name)
            instance.name = data.name
        if data.url is not UNSET:
            instance.url = data.url.rstrip("/")
        if data.api_key is not UNSET:
            instance.api_key_encrypted = self.secret_box.encrypt_text(data.api_key)
        if data.enabled is not UNSET:
            instance.enabled = data.enabled
        if data.lingarr_instance_id is not UNSET:
            if data.lingarr_instance_id is not None:
                _ = await self.get_lingarr(data.lingarr_instance_id)
            instance.lingarr_instance_id = data.lingarr_instance_id
        await self.session.commit()
        return instance

    async def delete_bazarr(self, instance_id: UUID) -> None:
        _ = await self.get_bazarr(instance_id)
        _ = await self.bazarr_repo.delete(instance_id)
        await self.session.commit()

    async def store_bazarr_snapshot(
        self,
        instance_id: UUID,
        *,
        health: InstanceHealth | None = None,
        capabilities: BazarrCapabilities | None = None,
        version: str | None = None,
    ) -> None:
        instance = await self.get_bazarr(instance_id)
        if health is not None:
            instance.health_snapshot = _encode_json_column(health)
        if capabilities is not None:
            instance.capabilities = _encode_json_column(capabilities)
        if version is not None:
            instance.version = version
        await self.session.commit()

    # --- Lingarr ---------------------------------------------------------

    async def list_lingarr(self) -> list[LingarrInstance]:
        return list(await self.lingarr_repo.list(order_by=[("name", False)]))

    async def get_lingarr(self, instance_id: UUID) -> LingarrInstance:
        try:
            return await self.lingarr_repo.get(instance_id)
        except AANotFoundError as error:
            raise NotFoundError(f"Lingarr instance {instance_id} not found") from error

    def lingarr_api_key(self, instance: LingarrInstance) -> str | None:
        if instance.api_key_encrypted is None:
            return None
        return self.secret_box.decrypt_text(instance.api_key_encrypted)

    async def create_lingarr(
        self, data: LingarrInstanceCreate, *, version: str | None = None
    ) -> LingarrInstance:
        await self._ensure_unique_name(LingarrInstance, data.name)
        instance = LingarrInstance(
            name=data.name,
            url=data.url.rstrip("/"),
            api_key_encrypted=(
                self.secret_box.encrypt_text(data.api_key) if data.api_key else None
            ),
            enabled=data.enabled,
            version=version,
        )
        self.session.add(instance)
        await self.session.commit()
        return instance

    async def update_lingarr(
        self, instance_id: UUID, data: LingarrInstanceUpdate
    ) -> LingarrInstance:
        instance = await self.get_lingarr(instance_id)
        if data.name is not UNSET and data.name != instance.name:
            await self._ensure_unique_name(LingarrInstance, data.name)
            instance.name = data.name
        if data.url is not UNSET:
            instance.url = data.url.rstrip("/")
        if data.api_key is not UNSET:
            instance.api_key_encrypted = (
                self.secret_box.encrypt_text(data.api_key)
                if data.api_key is not None
                else None
            )
        if data.enabled is not UNSET:
            instance.enabled = data.enabled
        await self.session.commit()
        return instance

    async def delete_lingarr(self, instance_id: UUID) -> None:
        instance = await self.get_lingarr(instance_id)
        linked = list(
            await self.session.scalars(
                select(BazarrInstance.id).where(
                    BazarrInstance.lingarr_instance_id == instance_id
                )
            )
        )
        if linked:
            raise ConflictError(
                f"Lingarr instance is linked to {len(linked)} Bazarr instance(s); unlink them first"
            )
        await self.session.delete(instance)
        await self.session.commit()

    async def store_lingarr_snapshot(
        self,
        instance_id: UUID,
        *,
        health: InstanceHealth | None = None,
        version: str | None = None,
    ) -> None:
        instance = await self.get_lingarr(instance_id)
        if health is not None:
            instance.health_snapshot = _encode_json_column(health)
        if version is not None:
            instance.version = version
        await self.session.commit()

    # --- shared ----------------------------------------------------------

    async def _ensure_unique_name(
        self, model: type[BazarrInstance] | type[LingarrInstance], name: str
    ) -> None:
        existing = (
            await self.session.scalars(select(model.id).where(model.name == name))
        ).first()
        if existing is not None:
            raise ConflictError(f"an instance named {name!r} already exists")
