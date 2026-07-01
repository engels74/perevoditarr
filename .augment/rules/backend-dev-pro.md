---
type: "agent_requested"
description: "Litestar + Granian + msgspec + SQLAlchemy async Python backend coding guidelines"
---
# Litestar / Granian / msgspec / SQLAlchemy Async — Modern Python Backend Reference

This stack is a fully-typed, async-first, Rust-accelerated Python backend built for throughput and correctness. Litestar is the application framework, msgspec is the serialization/validation core (not Pydantic), Granian is the Rust HTTP server (not uvicorn/gunicorn), SQLAlchemy 2.0 async over asyncpg is the persistence layer (usually via Advanced Alchemy's repository/service layer), and the tooling is the Astral/DetachHead trio — uv, ruff, and basedpyright. Optimize for: async everywhere (never block the event loop), msgspec `Struct`s and SQLAlchemy DTOs instead of hand-written serializers, eager relationship loading (lazy loading raises under async), long-lived connection pools and HTTP clients, and strict typing that basedpyright's `recommended` mode actually enforces.

The single biggest way agents write wrong-but-plausible code here is importing habits from FastAPI/Pydantic/Flask/Django. Concretely: reaching for `pydantic.BaseModel` where a `msgspec.Struct` belongs; running the app with `uvicorn`/`gunicorn` instead of Granian's `litestar run`; writing `session.query(...)` (legacy 1.x) instead of `select()` + `session.execute()`; accessing `obj.related` and triggering a lazy load that throws `MissingGreenlet`; instantiating `httpx.AsyncClient()` per request; and using `pip`/`poetry`/`black`/`isort`/`flake8`/`mypy` where `uv`/`ruff`/`basedpyright` are the stack's tools. Every section below shows the idiomatic path once and well.

## Stack snapshot (mid-2026)

- **Research date:** July 1, 2026
- **Research basis:** current official docs, release notes, specifications, changelogs, and primary repositories.

| Component | Current stable | Notes |
|---|---|---|
| Python | 3.14.x | Deferred annotations (PEP 649/749) on by default; free-threading officially supported (PEP 779) but opt-in; JIT still experimental |
| Litestar | 2.24.0 | 2.x is current; 3.0 not yet stable |
| Granian | 2.7.x | Default interface is `rsgi` |
| litestar-granian | 0.15.x | First-party plugin |
| msgspec | 0.21.x | Ships cp314 + free-threaded wheels |
| SQLAlchemy | 2.0.x (2.0.51) | 2.1 still in beta — target 2.0 |
| asyncpg | 0.31.x | PostgreSQL 9.5–18; cp314 wheels |
| advanced-alchemy | 1.11.x | Repository/service layer for Litestar |
| Alembic | 1.18.x | `async` and new `pyproject` templates |
| structlog | 26.x | Python 3.14/3.15 support |
| httpx | 0.28.x | 1.0 still pre-release |
| ruff | 0.15.x | 2026 style guide since 0.15.0 (released 2026-02-03) |
| uv | 0.11.x | PEP 735 dependency groups |
| basedpyright | 1.39.x | `recommended` mode is its default |

## Python 3.14 language baseline

Assume the 3.14 floor. The features that change how you write code:

**Deferred annotation evaluation (PEP 649/749, Python 3.14).** Annotations on functions, classes, and modules are no longer evaluated eagerly — they're stored in `__annotate__` functions and computed on demand. You no longer need to quote forward references or reach for `from __future__ import annotations`. That `__future__` import still works but is now redundant for most code; a critical exception in this stack is SQLAlchemy `Mapped[...]` models and Advanced Alchemy base modules, which introspect annotations at class-creation time — **do not** put `from __future__ import annotations` in model modules, but handlers/services/tests may use it freely. Use `annotationlib` (`get_annotations` with `Format.VALUE`/`FORWARDREF`/`STRING`) if you ever need to introspect annotations.

**PEP 695 type parameters & the `type` statement (Python 3.12+, standard by 3.14).** Prefer the native generic syntax:

```python
type UserId = int
type JsonMap = dict[str, "JsonValue"]

def first[T](items: list[T]) -> T | None:
    return items[0] if items else None

class Repository[ModelT]:
    def __init__(self, model: type[ModelT]) -> None:
        self.model = model
```

**Modern typing idioms** you should default to: `X | None` unions (never `Optional[X]`), builtin generics (`list[str]`, `dict[str, int]`), `Self` for fluent/factory returns, `override` on overriding methods (basedpyright's `recommended` flags missing ones), and `TypeIs`/`TypeGuard` for narrowing.

```python
from typing import Self, override

class Base:
    @classmethod
    def create(cls) -> Self:
        return cls()

class Child(Base):
    @override
    def __repr__(self) -> str:
        return "Child()"
```

**Exception groups & `except*` (Python 3.11+).** Relevant for concurrent async code (`asyncio.TaskGroup` raises `ExceptionGroup`). Handle typed sub-groups:

```python
try:
    async with asyncio.TaskGroup() as tg:
        tg.create_task(fetch_a())
        tg.create_task(fetch_b())
except* ValueError as eg:
    for exc in eg.exceptions:
        logger.warning("validation failed", error=str(exc))
except* ConnectionError as eg:
    ...
```

**t-strings / template strings (PEP 750, Python 3.14)** produce a `Template` object rather than a `str`, enabling safe custom interpolation (e.g. escaping) before rendering. Do not treat a t-string as a drop-in `str`; it is a distinct type consumed by a processor.

**Free-threading (PEP 779) is officially supported in 3.14 but opt-in** via a separate `python3.14t` binary — it is not the default and single-threaded code pays a measurable penalty. The **JIT remains experimental**. Do not depend on either free-threading or the JIT in production defaults; this async I/O-bound stack scales via the event loop and Granian workers, not threads. Subinterpreters are now in the stdlib via `concurrent.interpreters` (PEP 734) — a niche tool, not part of the normal request path here.

## Application construction & routing (Litestar 2.x)

A Litestar app is a collection of route handlers, plugins, and layered config. Unlike FastAPI (a thin layer over Starlette), Litestar has no Starlette dependency and uses msgspec — not Pydantic — as its native data layer.

```python
from litestar import Litestar, get, post
from litestar_granian import GranianPlugin

@get("/health", sync_to_thread=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}

app = Litestar(
    route_handlers=[health],
    plugins=[GranianPlugin()],
)
```

Handlers are decorated with `@get`, `@post`, `@put`, `@patch`, `@delete` (imported from `litestar`). Return values are serialized by msgspec automatically. Use `sync_to_thread=False` on non-blocking sync handlers to silence the warning and avoid a needless threadpool hop; use `sync_to_thread=True` only for genuinely blocking sync work.

**`Controller` classes** group related handlers under a shared path with shared dependencies/guards:

```python
from uuid import UUID
from litestar import Controller, get, post, patch, delete

class UserController(Controller):
    path = "/users"
    tags = ["users"]

    @get()
    async def list_users(self) -> list[UserRead]: ...

    @post()
    async def create_user(self, data: UserCreate) -> UserRead: ...

    @get("/{user_id:uuid}")
    async def get_user(self, user_id: UUID) -> UserRead: ...

    @patch("/{user_id:uuid}")
    async def update_user(self, user_id: UUID, data: UserUpdate) -> UserRead: ...

    @delete("/{user_id:uuid}")
    async def delete_user(self, user_id: UUID) -> None: ...
```

**Path parameters are typed with converters** in the path string: `{user_id:uuid}`, `{item_id:int}`, `{name:str}`, `{date:date}`, `{price:float}`, `{path_val:path}`. The converter drives both parsing and OpenAPI schema. **`Router`** groups controllers/handlers under a prefix, and routers nest:

```python
from litestar import Router

api_v1 = Router(path="/api/v1", route_handlers=[UserController, OrderController])
app = Litestar(route_handlers=[api_v1], plugins=[GranianPlugin()])
```

Litestar is **layered**: `dependencies`, `guards`, `middleware`, `before_request`, `after_response`, `exception_handlers`, and more can be set at app, router, controller, or handler level, with the most specific layer winning (except guards, which accumulate).

## msgspec: the serialization & validation core

msgspec replaces Pydantic in this stack. `msgspec.Struct` is a C-level slotted type that is dramatically faster than a Pydantic model — in msgspec author Jim Crist-Harif's published benchmark, "msgspec was roughly 6.4X faster for decode and 1.6X faster for encode" versus Pydantic v2, and per the official msgspec benchmarks, Struct operations run "roughly 5x to 60x faster than the alternatives" for common operations (Struct creation ~4x faster than standard classes/attrs/dataclasses and ~17x faster than Pydantic). Litestar validates request bodies and serializes responses through msgspec natively.

**The sharp behavioral difference from Pydantic:** a `Struct` constructor does **not** validate. `User(name=123)` will happily build a wrong instance; mypy/basedpyright is expected to catch that statically. Validation happens only at the decode boundary — `msgspec.json.decode(data, type=User)` — which is exactly where untrusted input enters. Litestar wires that boundary for you.

```python
import msgspec
from typing import Annotated
from datetime import datetime

class UserCreate(msgspec.Struct, kw_only=True, forbid_unknown_fields=True):
    name: Annotated[str, msgspec.Meta(min_length=1, max_length=64)]
    email: Annotated[str, msgspec.Meta(pattern=r".+@.+\..+")]
    age: Annotated[int, msgspec.Meta(ge=0, le=150)] | None = None

class UserRead(msgspec.Struct, kw_only=True, omit_defaults=True):
    id: str
    name: str
    email: str
    created_at: datetime
```

Key `Struct` config flags (set as class kwargs): `frozen=True` (immutable + hashable), `kw_only=True` (keyword-only init — recommended for readability and safe field ordering across inheritance), `omit_defaults=True` (skip default-valued fields when encoding — smaller payloads, faster), `forbid_unknown_fields=True` (reject unexpected keys on decode — use for request bodies), `rename="camel"` (emit camelCase JSON while keeping snake_case Python), and `tag`/`tag_field` for tagged unions.

**Constraints go in `Annotated` with `msgspec.Meta`**, not in field definitions like Pydantic's `Field`. Reusable constrained aliases read well:

```python
PositiveInt = Annotated[int, msgspec.Meta(gt=0)]
Slug = Annotated[str, msgspec.Meta(pattern=r"^[a-z0-9-]+$", max_length=100)]
```

**Tagged unions** (discriminated unions) — set a `tag` on each member; msgspec adds a discriminator field (default name `"type"`) and dispatches on decode:

```python
class Cat(msgspec.Struct, tag="cat"):
    meows: int

class Dog(msgspec.Struct, tag="dog"):
    barks: int

Animal = Cat | Dog
msgspec.json.decode(b'{"type":"cat","meows":3}', type=Animal)  # -> Cat(meows=3)
```
Always tag every member of a union; an untagged union forces msgspec to try each variant and is ambiguous when fields overlap.

**`msgspec.field()`** configures per-field defaults/renames: `field(default_factory=list)`, `field(name="userName")`. **`UNSET` / `msgspec.UNSET`** distinguishes "field absent" from "field explicitly null" — essential for PATCH semantics:

```python
from msgspec import UNSET, UnsetType

class UserPatch(msgspec.Struct, kw_only=True):
    name: str | UnsetType = UNSET
    email: str | UnsetType = UNSET
```

**Performance path:** for hot loops, build a reusable `Encoder`/`Decoder` once rather than calling the module-level functions repeatedly:

```python
decoder = msgspec.json.Decoder(UserCreate)
encoder = msgspec.json.Encoder()
user = decoder.decode(raw_bytes)
payload = encoder.encode(user)
```

**Struct helpers:** `msgspec.structs.replace(obj, **changes)` (immutable update), `msgspec.structs.asdict(obj)` / `astuple(obj)`, and `msgspec.convert(obj, Type, from_attributes=True)` to coerce e.g. ORM rows into structs. **`msgspec.Raw`** defers decoding of a field (holds the raw bytes). Custom types are handled with `enc_hook`/`dec_hook`. Do not reach for `.model_dump()`, `.dict()`, `BaseModel`, `Field(...)`, `@validator`, or `ConfigDict` — those are Pydantic and do not exist here.

## Data handling with DTOs

Litestar's DTO system transforms between wire format and your domain objects, driven by `dto=` (inbound) and `return_dto=` (outbound) on handlers/controllers. Any type inheriting `AbstractDTO` works; the factories you'll use are `MsgspecDTO`, `DataclassDTO`, and — most importantly here — `SQLAlchemyDTO` (from `advanced_alchemy.extensions.litestar` / re-exported at `litestar.plugins.sqlalchemy`). The `SQLAlchemyDTO` lets you return ORM models directly from handlers without an intermediate schema.

```python
from datetime import datetime
from typing import Annotated
from sqlalchemy.orm import Mapped, mapped_column
from litestar import post
from litestar.dto import DTOConfig, dto_field
from litestar.plugins.sqlalchemy import SQLAlchemyDTO
from advanced_alchemy.base import UUIDAuditBase

class User(UUIDAuditBase):
    __tablename__ = "user_account"
    name: Mapped[str]
    password: Mapped[str] = mapped_column(info=dto_field("private"))       # never serialized
    created_at: Mapped[datetime] = mapped_column(info=dto_field("read-only"))

config = DTOConfig(
    exclude={"password"},
    rename_fields={"name": "userName"},
    max_nested_depth=1,
)
UserWriteDTO = SQLAlchemyDTO[Annotated[User, config]]

@post("/users", dto=UserWriteDTO, return_dto=SQLAlchemyDTO[User])
async def create_user(data: User) -> User:
    return data
```

`DTOConfig` supports `include`/`exclude` (field sets), `rename_fields`, `rename_strategy` (`"camel"` etc.), `max_nested_depth`, and `partial=True` (all fields optional — for PATCH). Mark columns `dto_field("private")` (never read/write) or `dto_field("read-only")` (serialized out, ignored on input) directly on the model. For partial updates, type the handler `data` param as `DTOData[SomeDTO]` and call `.create_instance()` / `.update_instance(obj)`.

## Dependency injection

Litestar's DI is pytest-inspired: named providers wrapped in `Provide`, injected by matching parameter name. Providers may be sync or async, and are declared at any layer.

```python
from litestar import Litestar, get
from litestar.di import Provide

async def provide_user_service(db_session: AsyncSession) -> UserService:
    return UserService(session=db_session)

@get("/users/{user_id:uuid}")
async def get_user(user_id: UUID, user_service: UserService) -> UserRead:
    return await user_service.get(user_id)

app = Litestar(
    route_handlers=[get_user],
    dependencies={"user_service": Provide(provide_user_service)},
)
```

Dependencies **nest** — a provider can itself declare dependencies by name, as `provide_user_service` does with `db_session`. By default a dependency is invoked once per request even without caching. `Provide(fn, use_cache=True)` memoizes the return across the app/connection lifetime (no kwargs-aware LRU — use it for expensive, argument-independent singletons like a config object or a shared client). For sync providers that don't block, pass `sync_to_thread=False` to avoid the threadpool. Override a dependency at a more specific layer simply by re-declaring the same name; unlike guards, dependencies override rather than accumulate.

## SQLAlchemy 2.0 async + asyncpg

Use the 2.0 style exclusively: `select()` statements executed through an `AsyncSession`. The legacy `session.query(...)` Query API is 1.x and must not be used.

**Engine & session.** One engine per process; short-lived sessions per unit of work; `expire_on_commit=False` is effectively mandatory under async (otherwise attributes expire after commit and re-accessing them triggers a lazy load that raises).

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

engine = create_async_engine(
    "postgresql+asyncpg://app:pwd@localhost:5432/app",
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=1800,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
```

The `postgresql+asyncpg://` URL selects the asyncpg driver, which MagicStack benchmarks as, on average, "5x faster than psycopg3" — the correct default for this stack. psycopg3 async (`postgresql+psycopg://`) is the adjacent alternative but not the default here. When running behind **pgbouncer in transaction/statement pooling mode**, or on serverless, disable SQLAlchemy's pool with `poolclass=NullPool` and disable asyncpg's prepared-statement cache to avoid cross-connection statement collisions.

**Modern declarative models** use `Mapped[...]` + `mapped_column()`; relationships are typed `Mapped[list["Child"]]` / `Mapped["Parent"]`. Include `AsyncAttrs` on the base so you have an escape hatch for awaited lazy loads.

```python
from datetime import datetime
from sqlalchemy import ForeignKey, func, String
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(AsyncAttrs, DeclarativeBase):
    pass

class Author(Base):
    __tablename__ = "author"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    books: Mapped[list["Book"]] = relationship(back_populates="author")

class Book(Base):
    __tablename__ = "book"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    author_id: Mapped[int] = mapped_column(ForeignKey("author.id"))
    author: Mapped[Author] = relationship(back_populates="books")
```

**Querying** uses `select()` + `session.execute()`/`session.scalars()`:

```python
from sqlalchemy import select
from sqlalchemy.orm import selectinload

async with async_session() as session:
    stmt = (
        select(Author)
        .where(Author.name == "Ada")
        .options(selectinload(Author.books))
    )
    author = (await session.scalars(stmt)).one_or_none()
```

Use `.scalar_one()` (exactly one, else raises), `.scalar_one_or_none()`, or `session.scalars(...).all()`.

**The async lazy-loading rule is the number-one gotcha.** Accessing an unloaded relationship or an expired attribute outside an awaitable context raises `MissingGreenlet`. You must eager-load. Strategy choice:

| Strategy | Emits | Use when |
|---|---|---|
| `selectinload` | Second `IN` query per relationship | Collections (one-to-many, many-to-many); avoids row multiplication |
| `joinedload` | Single `LEFT OUTER JOIN` | Many-to-one / one-to-one scalar relationships |
| `subqueryload` | Correlated subquery | Legacy; prefer `selectinload` |
| `lazy="raise"` | Raises on access | Default guard to catch accidental N+1 at dev time |

The escape hatch when you genuinely need one lazy attribute: `await obj.awaitable_attrs.books` (requires `AsyncAttrs`). For running sync ORM code inside async, use `await session.run_sync(fn)`.

**Transactions** — wrap writes in `async with session.begin()` for an automatic commit/rollback boundary:

```python
async with async_session() as session, session.begin():
    session.add(Author(name="Grace"))
    # commits on clean exit, rolls back on exception
```

**Bulk / upsert** use `insert().returning()` and the PostgreSQL dialect's `on_conflict_do_update`:

```python
from sqlalchemy.dialects.postgresql import insert

stmt = (
    insert(Author)
    .values([{"name": "A"}, {"name": "B"}])
    .on_conflict_do_update(index_elements=["name"], set_={"name": insert.excluded.name})
    .returning(Author.id)
)
ids = (await session.scalars(stmt)).all()
```

**PostgreSQL-specific types** — `JSONB`, `ARRAY` from `sqlalchemy.dialects.postgresql`:

```python
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy import Integer, String

class Event(Base):
    __tablename__ = "event"
    id: Mapped[int] = mapped_column(primary_key=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String))
    scores: Mapped[list[int]] = mapped_column(ARRAY(Integer))
```

`Mapped[]` typing is what makes basedpyright understand your columns as their Python types — `Mapped[str]` reads as `str` on an instance, so no casts are needed for attribute access.

## Advanced Alchemy: repositories, services & the Litestar plugin

Advanced Alchemy is the Litestar team's official SQLAlchemy companion and the idiomatic persistence layer for this stack. It provides audit-ready base classes, generic async repositories/services, and the `SQLAlchemyPlugin` that wires session dependency injection and transaction handling into Litestar. Install via `litestar[sqlalchemy]` or `advanced-alchemy` directly.

**Base classes** (pick per primary-key strategy): `UUIDBase`/`UUIDAuditBase` (UUID PK; audit adds `created_at`/`updated_at`), `UUIDv7Base`/`UUIDv7AuditBase`, `BigIntBase`/`BigIntAuditBase`, `NanoIDBase`. Default to `UUIDAuditBase` unless you have a reason not to. **Note:** model modules must **not** use `from __future__ import annotations` because `Mapped[...]` is introspected at class-creation.

```python
from datetime import date
from uuid import UUID
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from advanced_alchemy.base import UUIDAuditBase

class Author(UUIDAuditBase):
    __tablename__ = "author"
    name: Mapped[str]
    dob: Mapped[date | None]
    books: Mapped[list["Book"]] = relationship(back_populates="author", lazy="selectin")

class Book(UUIDAuditBase):
    __tablename__ = "book"
    title: Mapped[str]
    author_id: Mapped[UUID] = mapped_column(ForeignKey("author.id"))
    author: Mapped[Author] = relationship(back_populates="books", lazy="joined", innerjoin=True)
```

**Repository** — generic CRUD, pagination, filtering, optimized bulk ops derived from the model:

```python
from advanced_alchemy.repository import SQLAlchemyAsyncRepository

class AuthorRepository(SQLAlchemyAsyncRepository[Author]):
    model_type = Author
```

You get `get`, `get_one`, `get_one_or_none`, `list`, `list_and_count`, `add`, `add_many`, `update`, `upsert`, `delete`, `delete_many` for free, with dialect-aware bulk operations and RETURNING support auto-detected.

**Service** layer wraps a repository and handles DTO↔model transformation and lifecycle hooks:

```python
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService

class AuthorService(SQLAlchemyAsyncRepositoryService[Author]):
    class Repo(SQLAlchemyAsyncRepository[Author]):
        model_type = Author
    repository_type = Repo
```

**Plugin wiring** provides the `db_session` dependency and configures the engine:

```python
from litestar import Litestar
from advanced_alchemy.extensions.litestar import (
    SQLAlchemyPlugin, SQLAlchemyAsyncConfig, AsyncSessionConfig,
)

alchemy = SQLAlchemyPlugin(
    config=SQLAlchemyAsyncConfig(
        connection_string="postgresql+asyncpg://app:pwd@localhost/app",
        session_config=AsyncSessionConfig(expire_on_commit=False),
        create_all=False,  # use Alembic for schema, not create_all, in production
    )
)
app = Litestar(route_handlers=[...], plugins=[alchemy])
```

Then inject `db_session: AsyncSession` (or a provided service) into handlers. Advanced Alchemy also ships a UTC `DateTimeUTC` type, a database-agnostic JSON type (JSONB on PostgreSQL), `EncryptedString`, and a `FileObject` type with fsspec/obstore backends.

## Granian + litestar-granian: the server

Granian is "A Rust HTTP server for Python applications built on top of the Hyper crate" that runs WSGI, ASGI, and its own **RSGI** protocol, with native HTTP/1.1 + HTTP/2. It is the modern replacement for the uvicorn/gunicorn combination, explicitly designed to "avoid the usual Gunicorn + uvicorn + http-tools dependency composition": single binary, native HTTP/2 without extra libraries, lower memory, and higher throughput. RSGI avoids the per-request ASGI scope-dict allocations by passing a Rust-backed object; Litestar has first-class RSGI support. Granian's default interface is `rsgi` (`--interface [asgi|asginl|rsgi|wsgi]`, `GRANIAN_INTERFACE`, default `rsgi`).

**Do not reach for uvicorn or gunicorn.** In this stack the app is launched by `litestar run`, and the `litestar-granian` plugin makes that command drive Granian instead of uvicorn — same CLI, same lifespan/signal/reload integration.

```python
from litestar import Litestar
from litestar_granian import GranianPlugin

app = Litestar(route_handlers=[...], plugins=[GranianPlugin()])
```

```bash
# Dev, with autoreload
litestar run --reload

# Production: match workers to cores, bind publicly
litestar run --host 0.0.0.0 --port 8000 --workers 8
```

For async (ASGI/RSGI) workloads use runtime-threaded mode; scaling is driven by the number of event loops (workers), not blocking threads. Set worker count to CPU cores; set backpressure limits in production so traffic spikes don't cause unbounded queuing and OOM. The cardinal rule: **never do blocking I/O inside an `async def` handler** — a blocking DB or HTTP call starves Granian's event loop and stalls the worker. Prefer the plugin over invoking the bare `granian` CLI for Litestar apps, so the server lifecycle stays wired to Litestar.

## Middleware, guards & authentication

**Middleware** uses the ASGI factory pattern (a callable taking the next ASGI app and returning an ASGI app) or `AbstractMiddleware`; register with `DefineMiddleware` for arguments. Middleware runs in declaration order and can be layered.

```python
from litestar.middleware import AbstractMiddleware
from litestar.types import Receive, Scope, Send

class TimingMiddleware(AbstractMiddleware):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # ... measure ...
        await self.app(scope, receive, send)
```

**Guards** are callables `(connection, handler) -> None` that authorize a request, raising `NotAuthorizedException`/`PermissionDeniedException` on failure. They accumulate across layers (all guards on the path run).

```python
from litestar.connection import ASGIConnection
from litestar.handlers.base import BaseRouteHandler
from litestar.exceptions import NotAuthorizedException

def require_admin(connection: ASGIConnection, handler: BaseRouteHandler) -> None:
    if not getattr(connection.user, "is_admin", False):
        raise NotAuthorizedException()
```

**JWT authentication** ships in `litestar.security.jwt`. Construct a `JWTAuth` (header bearer) or `JWTCookieAuth` / `OAuth2PasswordBearerAuth`, and register via `on_app_init`. `retrieve_user_handler` maps a decoded token to your user object, which becomes `request.user`; `request.auth` holds the `Token`.

```python
from litestar import Litestar, post, Response
from litestar.connection import ASGIConnection
from litestar.security.jwt import JWTAuth, Token

async def retrieve_user_handler(token: Token, connection: ASGIConnection) -> User | None:
    return await load_user(token.sub)

jwt_auth = JWTAuth[User](
    retrieve_user_handler=retrieve_user_handler,
    token_secret="...",           # load from environment
    exclude=["/login", "/schema"],
)

@post("/login")
async def login(data: LoginData) -> Response[User]:
    user = await authenticate(data)
    return jwt_auth.login(identifier=str(user.id), token_extras={"email": user.email}, response_body=user)

app = Litestar(route_handlers=[login], on_app_init=[jwt_auth.on_app_init])
```

For lower-level needs subclass `AbstractAuthenticationMiddleware`. Built-in `CORSConfig`, `CSRFConfig`, `RateLimitConfig`, `CompressionConfig`, and `AllowedHostsConfig` cover the standard cross-cutting concerns and are passed to `Litestar(...)`.

## Lifecycle, state, exceptions & responses

**Lifespan** for setup/teardown of long-lived resources (HTTP clients, pools) uses an async context manager; store handles on `app.state`:

```python
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
import httpx
from litestar import Litestar
from litestar.datastructures import State

@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None, None]:
    app.state.http = httpx.AsyncClient(timeout=10.0)
    try:
        yield
    finally:
        await app.state.http.aclose()

app = Litestar(route_handlers=[...], lifespan=[lifespan])
```

Inject app state into a handler by typing a `state: State` parameter. There are also `on_startup`/`on_shutdown` hooks and `before_request`/`after_request`/`after_response` hooks at every layer.

**Exception handling** maps exception types to handlers via `exception_handlers=`; raise `HTTPException` subclasses (`NotFoundException`, `ValidationException`, `NotAuthorizedException`, etc.) for standard responses.

```python
from litestar import Request, Response

def handle_domain_error(request: Request, exc: DomainError) -> Response:
    return Response({"detail": str(exc)}, status_code=422)

app = Litestar(route_handlers=[...], exception_handlers={DomainError: handle_domain_error})
```

**Response types** beyond plain return values: `Response` (explicit status/headers/cookies), `Redirect`, `File`, `Stream` (async iterator), `ServerSentEvent`, and `Template`. Background work runs via `BackgroundTask`/`BackgroundTasks` attached to a response.

```python
from litestar import get
from litestar.response import Stream, ServerSentEvent

@get("/download")
async def download() -> Stream:
    async def gen():
        yield b"chunk-1"
        yield b"chunk-2"
    return Stream(gen(), media_type="application/octet-stream")

@get("/events")
async def events() -> ServerSentEvent:
    async def publisher():
        yield "tick"
    return ServerSentEvent(publisher())
```

## OpenAPI

Litestar generates an OpenAPI 3.1.0 schema automatically from your handler signatures and msgspec/SQLAlchemy types. Configure via `OpenAPIConfig`. In Litestar 2.x several UI renderers are available and can be enabled by adding render plugins; the schema JSON is served at `/schema/openapi.json` and UIs under `/schema/*`.

```python
from litestar import Litestar
from litestar.openapi import OpenAPIConfig
from litestar.openapi.plugins import ScalarRenderPlugin, SwaggerRenderPlugin

app = Litestar(
    route_handlers=[...],
    openapi_config=OpenAPIConfig(
        title="My API",
        version="1.0.0",
        render_plugins=[ScalarRenderPlugin(), SwaggerRenderPlugin()],
    ),
)
```

Scalar is the Litestar project's preferred UI (and becomes the single default in the upcoming 3.0). Available render plugins include `ScalarRenderPlugin`, `SwaggerRenderPlugin`, `RedocRenderPlugin`, `RapidocRenderPlugin`, and `StoplightRenderPlugin`. Refine per-parameter schema with `Parameter(...)` and request bodies with `Body(...)`.

## Parameters & request data

Query, header, and cookie parameters are declared with `Parameter`; request bodies with `Body`; and DI-only values with `Dependency`. A bare typed parameter that matches no path parameter is treated as a query parameter.

```python
from typing import Annotated
from litestar import get, post
from litestar.params import Parameter, Body
from litestar.enums import RequestEncodingType

@get("/search")
async def search(
    q: str,
    limit: Annotated[int, Parameter(ge=1, le=100)] = 20,
    x_request_id: Annotated[str | None, Parameter(header="X-Request-ID")] = None,
) -> list[Result]: ...

@post("/upload")
async def upload(
    data: Annotated[dict, Body(media_type=RequestEncodingType.MULTI_PART)],
) -> None: ...
```

## structlog logging

Use Litestar's `StructlogPlugin`, which wires request-scoped structured logging and gives every handler a `request.logger`. Configure JSON rendering in production and console rendering in dev; bind request context via contextvars.

```python
from litestar import Litestar, Request, get
from litestar.plugins.structlog import StructlogPlugin

@get("/")
async def index(request: Request) -> None:
    request.logger.info("handled", path="/", user="anon")

app = Litestar(route_handlers=[index], plugins=[StructlogPlugin()])
```

For control over the processor chain, pass a `StructlogConfig` wrapping a `StructLoggingConfig` (which exposes `processors`, `wrapper_class`, `logger_factory`, `cache_logger_on_first_use`, `log_exceptions`). A standalone structlog config for JSON output uses the stdlib bridge so third-party logs share the format:

```python
import structlog

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),   # ConsoleRenderer() in dev
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)
```

Bind per-request context with `structlog.contextvars.bind_contextvars(request_id=...)` — contextvars are async-safe and flow through the event loop. Prefer `WriteLogger`/stdlib output over `PrintLogger` under Granian so log lines aren't interleaved or lost. Do not use bare `logging.getLogger().info("msg %s", x)` %-style calls; log events with structured key-values.

## httpx: outbound HTTP

Use `httpx.AsyncClient` as a long-lived object created at startup and closed at shutdown (see the lifespan example) — never instantiate one per request, which throws away connection pooling and TLS reuse. Configure timeouts and pool limits explicitly. `requests` is the sync/legacy library and must not be used in this async stack.

```python
import httpx

client = httpx.AsyncClient(
    base_url="https://api.example.com",
    timeout=httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=3.0),
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=30.0),
    http2=True,
)

resp = await client.get("/users")
resp.raise_for_status()
data = resp.json()
```

Stream large responses with `async with client.stream("GET", url) as resp: async for chunk in resp.aiter_bytes(): ...`. Retries/custom behavior go through a custom `AsyncHTTPTransport(retries=...)`. For in-process testing against your Litestar app without a socket, use `httpx.ASGITransport`:

```python
transport = httpx.ASGITransport(app=app)
async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
    r = await client.get("/health")
```

## Testing

Litestar ships test clients built on httpx: `TestClient` (sync), `AsyncTestClient` (async), and the `create_test_client` helper for quick, dependency-overriding setups. Use `subprocess_sync_client`/`AsyncTestClient` with a live server when you need real Granian behavior.

```python
from litestar.testing import create_test_client

def test_health() -> None:
    with create_test_client(route_handlers=[health]) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
```

```python
import pytest
from litestar.testing import AsyncTestClient

@pytest.mark.asyncio
async def test_users() -> None:
    async with AsyncTestClient(app=app) as client:
        resp = await client.get("/api/v1/users")
        assert resp.status_code == 200
```

Override dependencies by passing `dependencies={...}` to the test client to inject test doubles (e.g. a session bound to a rolled-back transaction).

## Alembic migrations (async)

Initialize with the async template so `env.py` uses an async engine. Alembic 1.16+ also offers a `pyproject` template that keeps config in `pyproject.toml`.

```bash
alembic init -t async migrations
```

Set naming conventions on your `MetaData` so autogenerated constraints have stable, predictable names (critical for reversible migrations) — define them on the Base's metadata:

```python
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
```

In `migrations/env.py`, import your models so their metadata is populated, set `target_metadata = Base.metadata`, and read the async URL. The async template already runs migrations through `connection.run_sync(do_run_migrations)` inside an `AsyncEngine`. Typical loop:

```bash
alembic revision --autogenerate -m "add author table"
alembic upgrade head
```

Always review autogenerated scripts — Alembic reliably detects table/column adds/removes and nullability but not every change (e.g. some type changes). Advanced Alchemy ships its own Alembic configuration/CLI integration that plays with its base models if you prefer that path.

## uv: project & dependency management

uv is the Rust project/package manager — it replaces pip, pip-tools, poetry, pdm, and virtualenv management with one fast tool backed by `pyproject.toml` + `uv.lock`. Use `[dependency-groups]` (PEP 735) for dev-only tools, `uv add`/`remove`/`sync`/`lock`/`run`, and `uv python pin` to fix the interpreter.

```bash
uv init myapp
uv python pin 3.14
uv add litestar granian litestar-granian msgspec "sqlalchemy[asyncio]" asyncpg advanced-alchemy alembic structlog httpx
uv add --dev ruff basedpyright pytest pytest-asyncio
uv sync
uv run litestar run
uvx ruff check .        # run a tool ephemerally without installing into the project
```

A representative `pyproject.toml`:

```toml
[project]
name = "myapp"
version = "0.1.0"
requires-python = ">=3.14"
dependencies = [
    "litestar>=2.24",
    "granian>=2.7",
    "litestar-granian>=0.15",
    "msgspec>=0.21",
    "sqlalchemy[asyncio]>=2.0.51",
    "asyncpg>=0.31",
    "advanced-alchemy>=1.11",
    "alembic>=1.18",
    "structlog>=26",
    "httpx>=0.28",
]

[dependency-groups]
dev = [
    "ruff>=0.15",
    "basedpyright>=1.39",
    "pytest>=8",
    "pytest-asyncio>=1",
]

[tool.uv]
# uv-specific resolver settings go here if needed
```

`uv.lock` pins exact resolved versions for reproducible installs; commit it. `requires-python` doubles as ruff's inferred target version.

## ruff: lint + format

ruff is the single linter + formatter, replacing black, isort, flake8, pyupgrade, and pydocstyle. `ruff format` is the black-compatible formatter; `ruff check --fix` lints and autofixes. Ruff v0.15.0 (released 2026-02-03) introduced the new 2026 style guide, including unparenthesized `except A, B, C` (PEP 758) for target-version 3.14+. Configure in `pyproject.toml`:

```toml
[tool.ruff]
line-length = 88
target-version = "py314"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "C4", "ASYNC", "RUF"]
ignore = ["E501"]  # let the formatter own line length

[tool.ruff.lint.isort]
known-first-party = ["myapp"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
skip-magic-trailing-comma = false
```

`UP` modernizes syntax (old unions → `X | Y`, etc.), `ASYNC` catches blocking calls in async functions (directly relevant to the "don't block the event loop" rule), `B` catches bugbears, `SIM` simplifies. Run `uv run ruff check --fix .` then `uv run ruff format .`; wire the official `ruff-pre-commit` hooks (`ruff-check` with `--fix`, then `ruff-format`).

## basedpyright: type checking

basedpyright is the stricter pyright fork and the type checker for this stack. Its default `typeCheckingMode` is `recommended` (a level above pyright's `standard`/`strict` scale) and it adds rules pyright lacks — `reportAny`, `reportExplicitAny`, `reportIgnoreCommentWithoutRule`, `reportUnreachable`. It ships a bundled Node runtime via the PyPI wheel, so no separate npm install. Prefer it over plain pyright or mypy.

```toml
[tool.basedpyright]
pythonVersion = "3.14"
typeCheckingMode = "recommended"
include = ["src", "tests"]
reportMissingTypeStubs = false
```

Run with `uv run basedpyright`. Because `recommended` enables `reportIgnoreCommentWithoutRule`, every suppression must name its rule: use `# pyright: ignore[reportAny]`, not a bare `# type: ignore`. `reportAny`/`reportExplicitAny` push you off `Any`; where a third-party API unavoidably returns `Any`, suppress narrowly at that line. This mode pairs well with the stack: SQLAlchemy `Mapped[str]` resolves to `str` on instances, msgspec `Struct`s are fully typed (constructor calls are statically checked — the compensation for no runtime constructor validation), and Litestar's handler signatures are introspected as real types. For an existing codebase adopting strict rules, `basedpyright --writebaseline` records current diagnostics so you enforce the ceiling without fixing everything at once.

## Anti-patterns to avoid

| Wrong (adjacent-ecosystem habit) | Right (this stack) |
|---|---|
| `from pydantic import BaseModel` for schemas | `class X(msgspec.Struct)` |
| `Field(gt=0)` / `@validator` | `Annotated[int, msgspec.Meta(gt=0)]` |
| `uvicorn app:app` / `gunicorn -k uvicorn.workers...` | `litestar run` with `GranianPlugin` |
| `session.query(User).filter_by(...)` | `select(User).where(...)` + `session.scalars()` |
| Accessing `author.books` unloaded under async | `selectinload(Author.books)` or `await author.awaitable_attrs.books` |
| `expire_on_commit=True` (default) under async | `expire_on_commit=False` |
| `httpx.AsyncClient()` per request | one long-lived client on `app.state`, closed in lifespan |
| `import requests` | `httpx.AsyncClient` |
| Blocking I/O inside `async def` | async driver/client, or `run_sync`/threadpool |
| `pip install` / `poetry add` | `uv add` / `uv sync` |
| `black . && isort . && flake8` | `ruff format` + `ruff check --fix` |
| `mypy` / plain `pyright` | `basedpyright` (`recommended`) |
| bare `# type: ignore` | `# pyright: ignore[reportX]` |
| `from __future__ import annotations` in ORM model modules | omit it in model modules (Mapped introspection); fine elsewhere |
| `Optional[X]` / `List[X]` | `X | None` / `list[X]` |
| `create_all` for prod schema | Alembic migrations (`upgrade head`) |
| Untagged `Struct` unions | `tag="..."` on every union member |
