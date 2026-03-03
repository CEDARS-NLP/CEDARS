# CEDARS v2 Platform Reimplementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reimplement CEDARS as a multi-tenant platform on FastAPI + React + PostgreSQL with unified evaluation for all predictor types.

**Architecture:** Strangler fig migration — new FastAPI backend (`backend/`) and React frontend (`frontend/`) built alongside existing Flask app (`cedars/`). Each phase migrates one domain. Old Flask app removed after all domains migrated.

**Tech Stack:** FastAPI, SQLAlchemy 2.0+SQLModel, Alembic, PostgreSQL 16, ARQ, React 18+TypeScript, Vite, shadcn/ui, TanStack Query, boto3 (S3), Docker Compose.

**Design Doc:** `docs/plans/2026-03-03-cedars-v2-platform-redesign.md`

---

## Phase Overview

| Phase | Domain | Depends On |
|-------|--------|-----------|
| **0** | Project scaffolding (backend + frontend + Docker) | — |
| **1** | Auth + User management | Phase 0 |
| **2** | Project management + multi-tenancy | Phase 1 |
| **3** | Data connectors + ingestion | Phase 2 |
| **4** | Predictor system (LLM + PINES) | Phase 2 |
| **5** | NLP pipeline (spaCy preprocessing) | Phase 3 |
| **6** | Annotations + adjudication UI | Phase 4, 5 |
| **7** | Unified evaluation framework | Phase 4, 6 |
| **8** | Learning loops + training data export | Phase 7 |
| **9** | Export + monitoring | Phase 6 |
| **10** | MongoDB migration tool | Phase 2-9 |
| **11** | Remove Flask app | Phase 10 |

Each phase should be its own feature branch off `feature/llm-integration`.

---

## Phase 0: Project Scaffolding

### Task 0.1: Initialize Backend (FastAPI)

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py`
- Create: `backend/app/main.py`
- Create: `backend/app/config.py`

**Step 1: Create backend directory and pyproject.toml**

```bash
mkdir -p backend/app
```

```toml
# backend/pyproject.toml
[project]
name = "cedars-backend"
version = "2.0.0"
description = "CEDARS v2 Platform Backend"
requires-python = ">=3.10,<3.13"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "sqlalchemy[asyncio]>=2.0.0",
    "sqlmodel>=0.0.22",
    "alembic>=1.14.0",
    "asyncpg>=0.30.0",
    "pydantic-settings>=2.0.0",
    "python-jose[cryptography]>=3.3.0",
    "passlib[bcrypt]>=1.7.4",
    "boto3>=1.35.0",
    "redis>=5.0.0",
    "arq>=0.26.0",
    "litellm>=1.40.0",
    "httpx>=0.27.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=5.0.0",
    "httpx>=0.27.0",
    "ruff>=0.7.0",
    "testcontainers[postgres]>=4.0.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py310"
```

**Step 2: Create config module**

```python
# backend/app/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://cedars:cedars@localhost:5432/cedars"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Auth
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # S3-compatible storage
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "cedars"
    s3_access_key: str = "rootuser"
    s3_secret_key: str = "rootpassword"
    s3_region: str = "us-east-1"

    # PINES (optional)
    pines_api_url: str | None = None

    # LLM
    allow_cloud_llm: bool = True

    model_config = {"env_prefix": "CEDARS_", "env_file": ".env"}


settings = Settings()
```

**Step 3: Create FastAPI app factory**

```python
# backend/app/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown


def create_app() -> FastAPI:
    app = FastAPI(
        title="CEDARS Platform",
        version="2.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],  # Vite dev server
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/v1/health")
    async def health():
        return {"status": "ok", "version": "2.0.0"}

    return app


app = create_app()
```

```python
# backend/app/__init__.py
```

**Step 4: Verify backend runs**

```bash
cd backend && uv sync && uv run uvicorn app.main:app --reload --port 8000
```

Visit `http://localhost:8000/api/v1/health` — expect `{"status": "ok", "version": "2.0.0"}`.

**Step 5: Commit**

```bash
git add backend/
git commit -m "feat: scaffold FastAPI backend with config and health endpoint"
```

---

### Task 0.2: Database Setup (PostgreSQL + SQLAlchemy + Alembic)

**Files:**
- Create: `backend/app/common/__init__.py`
- Create: `backend/app/common/database.py`
- Create: `backend/alembic.ini`
- Create: `backend/migrations/env.py`
- Create: `backend/migrations/versions/` (directory)

**Step 1: Create database module**

```python
# backend/app/common/__init__.py
```

```python
# backend/app/common/database.py
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from app.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
```

**Step 2: Initialize Alembic**

```bash
cd backend && uv run alembic init migrations
```

Edit `backend/alembic.ini`:
- Set `sqlalchemy.url` to empty (will be set in env.py from config)

Edit `backend/migrations/env.py` to use async engine and import SQLModel metadata:

```python
# Key changes in migrations/env.py:
# - Import: from app.config import settings
# - Import: from sqlmodel import SQLModel
# - Set: target_metadata = SQLModel.metadata
# - Set: config.set_main_option("sqlalchemy.url", settings.database_url.replace("+asyncpg", ""))
# - Use async run_migrations_online()
```

**Step 3: Commit**

```bash
git add backend/app/common/ backend/alembic.ini backend/migrations/
git commit -m "feat: add PostgreSQL database layer with SQLAlchemy async and Alembic"
```

---

### Task 0.3: Write First Test (Backend Health Check)

**Files:**
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_health.py`

**Step 1: Create test infrastructure**

```python
# backend/tests/__init__.py
```

```python
# backend/tests/conftest.py
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
```

**Step 2: Write the failing test**

```python
# backend/tests/test_health.py
import pytest


@pytest.mark.asyncio
async def test_health_endpoint(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "2.0.0"
```

**Step 3: Run test**

```bash
cd backend && uv run pytest tests/test_health.py -v
```

Expected: PASS (health endpoint already exists from Task 0.1).

**Step 4: Commit**

```bash
git add backend/tests/
git commit -m "test: add backend test infrastructure and health check test"
```

---

### Task 0.4: Initialize Frontend (React + TypeScript + Vite)

**Files:**
- Create: `frontend/` (via Vite scaffold)
- Modify: `frontend/package.json` (add dependencies)
- Create: `frontend/src/App.tsx`

**Step 1: Scaffold React app with Vite**

```bash
cd /Users/rsingh/Programming/CEDARS
npm create vite@latest frontend -- --template react-ts
cd frontend && npm install
```

**Step 2: Install core dependencies**

```bash
cd frontend
npm install @tanstack/react-query react-router-dom
npm install -D tailwindcss @tailwindcss/vite
npm install -D @types/react-router-dom
```

**Step 3: Configure Tailwind**

Add Tailwind to `frontend/vite.config.ts`:

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
})
```

Add to `frontend/src/index.css`:
```css
@import "tailwindcss";
```

**Step 4: Create minimal App**

```typescript
// frontend/src/App.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Routes, Route } from 'react-router-dom'

const queryClient = new QueryClient()

function HomePage() {
  return (
    <div className="flex items-center justify-center min-h-screen">
      <h1 className="text-3xl font-bold">CEDARS Platform</h1>
    </div>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<HomePage />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
```

**Step 5: Verify frontend runs**

```bash
cd frontend && npm run dev
```

Visit `http://localhost:5173` — expect "CEDARS Platform" heading.

**Step 6: Commit**

```bash
git add frontend/
git commit -m "feat: scaffold React + TypeScript + Vite frontend with TanStack Query and routing"
```

---

### Task 0.5: Initialize shadcn/ui

**Files:**
- Modify: `frontend/` (shadcn init)

**Step 1: Initialize shadcn/ui**

```bash
cd frontend && npx shadcn@latest init
```

Select: TypeScript, Default style, CSS variables for colors.

**Step 2: Add core components**

```bash
npx shadcn@latest add button card input label form table
```

**Step 3: Commit**

```bash
git add frontend/
git commit -m "feat: initialize shadcn/ui with core components"
```

---

### Task 0.6: Docker Compose for v2 Stack

**Files:**
- Create: `docker-compose.v2.yml`

**Step 1: Write Docker Compose file**

```yaml
# docker-compose.v2.yml
# CEDARS v2 development stack
# Usage: docker compose -f docker-compose.v2.yml up
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: cedars
      POSTGRES_USER: cedars
      POSTGRES_PASSWORD: cedars
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U cedars"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

  minio:
    image: minio/minio:RELEASE.2024-05-10T01-41-38Z
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: rootuser
      MINIO_ROOT_PASSWORD: rootpassword
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - minio_data:/data
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  pgdata:
  minio_data:
```

**Step 2: Verify services start**

```bash
docker compose -f docker-compose.v2.yml up -d
docker compose -f docker-compose.v2.yml ps
```

All three services should be healthy.

**Step 3: Commit**

```bash
git add docker-compose.v2.yml
git commit -m "feat: add Docker Compose v2 stack (PostgreSQL, Redis, MinIO)"
```

---

### Task 0.7: Backend Dockerfiles

**Files:**
- Create: `backend/Dockerfile`
- Create: `frontend/Dockerfile`

**Step 1: Create backend Dockerfile**

```dockerfile
# backend/Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev

COPY . .

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 2: Create frontend Dockerfile**

```dockerfile
# frontend/Dockerfile
FROM node:20-alpine AS build

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

```nginx
# frontend/nginx.conf
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /ws/ {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

**Step 3: Commit**

```bash
git add backend/Dockerfile frontend/Dockerfile frontend/nginx.conf
git commit -m "feat: add Dockerfiles for backend and frontend"
```

---

## Phase 1: Auth + User Management

### Task 1.1: User Model

**Files:**
- Create: `backend/app/auth/__init__.py`
- Create: `backend/app/auth/models.py`
- Create: `backend/tests/test_auth.py`

**Step 1: Write failing test for User model**

```python
# backend/tests/test_auth.py
import pytest
from app.auth.models import User, UserRole


def test_user_model_creation():
    user = User(
        email="test@example.com",
        name="Test User",
        password_hash="hashed",
        role=UserRole.ADMIN,
    )
    assert user.email == "test@example.com"
    assert user.role == UserRole.ADMIN


def test_user_role_enum():
    assert UserRole.PLATFORM_ADMIN.value == "platform_admin"
    assert UserRole.USER.value == "user"
```

**Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_auth.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.auth'`

**Step 3: Implement User model**

```python
# backend/app/auth/__init__.py
```

```python
# backend/app/auth/models.py
import enum
from datetime import datetime
from uuid import uuid4

from sqlmodel import Field, SQLModel


class UserRole(str, enum.Enum):
    PLATFORM_ADMIN = "platform_admin"
    USER = "user"


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    email: str = Field(unique=True, index=True)
    name: str
    password_hash: str
    role: UserRole = Field(default=UserRole.USER)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

**Step 4: Run test to verify it passes**

```bash
cd backend && uv run pytest tests/test_auth.py -v
```

Expected: PASS

**Step 5: Create Alembic migration**

```bash
cd backend && uv run alembic revision --autogenerate -m "add users table"
uv run alembic upgrade head
```

**Step 6: Commit**

```bash
git add backend/app/auth/ backend/tests/test_auth.py backend/migrations/
git commit -m "feat: add User model with roles and Alembic migration"
```

---

### Task 1.2: Password Hashing Service

**Files:**
- Create: `backend/app/auth/service.py`
- Modify: `backend/tests/test_auth.py`

**Step 1: Write failing test**

```python
# Add to backend/tests/test_auth.py

from app.auth.service import hash_password, verify_password


def test_password_hashing():
    password = "secure-password-123"
    hashed = hash_password(password)
    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("wrong-password", hashed) is False
```

**Step 2: Run test — expect FAIL**

```bash
cd backend && uv run pytest tests/test_auth.py::test_password_hashing -v
```

**Step 3: Implement**

```python
# backend/app/auth/service.py
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)
```

**Step 4: Run test — expect PASS**

```bash
cd backend && uv run pytest tests/test_auth.py::test_password_hashing -v
```

**Step 5: Commit**

```bash
git add backend/app/auth/service.py backend/tests/test_auth.py
git commit -m "feat: add password hashing with bcrypt"
```

---

### Task 1.3: JWT Token Service

**Files:**
- Modify: `backend/app/auth/service.py`
- Modify: `backend/tests/test_auth.py`

**Step 1: Write failing test**

```python
# Add to backend/tests/test_auth.py

from app.auth.service import create_access_token, create_refresh_token, decode_token


def test_create_and_decode_access_token():
    token = create_access_token(user_id="user-123", role="user")
    payload = decode_token(token)
    assert payload["sub"] == "user-123"
    assert payload["role"] == "user"
    assert payload["type"] == "access"


def test_create_and_decode_refresh_token():
    token = create_refresh_token(user_id="user-123")
    payload = decode_token(token)
    assert payload["sub"] == "user-123"
    assert payload["type"] == "refresh"


def test_decode_invalid_token():
    payload = decode_token("invalid-token")
    assert payload is None
```

**Step 2: Run test — expect FAIL**

```bash
cd backend && uv run pytest tests/test_auth.py::test_create_and_decode_access_token -v
```

**Step 3: Implement**

```python
# Add to backend/app/auth/service.py
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.config import settings

ALGORITHM = "HS256"


def create_access_token(user_id: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": user_id, "role": role, "type": "access", "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    payload = {"sub": user_id, "type": "refresh", "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError:
        return None
```

**Step 4: Run tests — expect PASS**

```bash
cd backend && uv run pytest tests/test_auth.py -v
```

**Step 5: Commit**

```bash
git add backend/app/auth/service.py backend/tests/test_auth.py
git commit -m "feat: add JWT access and refresh token service"
```

---

### Task 1.4: Auth Schemas (Request/Response)

**Files:**
- Create: `backend/app/auth/schemas.py`

**Step 1: Create schemas**

```python
# backend/app/auth/schemas.py
from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    is_active: bool
```

**Step 2: Commit**

```bash
git add backend/app/auth/schemas.py
git commit -m "feat: add auth request/response schemas"
```

---

### Task 1.5: Auth Router (Register + Login)

**Files:**
- Create: `backend/app/auth/router.py`
- Modify: `backend/app/main.py` (register router)
- Create: `backend/tests/test_auth_api.py`

**Step 1: Write failing test**

```python
# backend/tests/test_auth_api.py
import pytest


@pytest.mark.asyncio
async def test_register_user(client):
    response = await client.post("/api/v1/auth/register", json={
        "email": "newuser@test.com",
        "name": "New User",
        "password": "securepass123",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "newuser@test.com"
    assert data["role"] == "user"
    assert "id" in data


@pytest.mark.asyncio
async def test_login_user(client):
    # Register first
    await client.post("/api/v1/auth/register", json={
        "email": "login@test.com",
        "name": "Login User",
        "password": "securepass123",
    })

    # Login
    response = await client.post("/api/v1/auth/login", json={
        "email": "login@test.com",
        "password": "securepass123",
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    await client.post("/api/v1/auth/register", json={
        "email": "wrong@test.com",
        "name": "Wrong User",
        "password": "securepass123",
    })

    response = await client.post("/api/v1/auth/login", json={
        "email": "wrong@test.com",
        "password": "wrongpass",
    })
    assert response.status_code == 401
```

**Step 2: Run test — expect FAIL**

```bash
cd backend && uv run pytest tests/test_auth_api.py -v
```

**Step 3: Update conftest.py for database testing**

```python
# backend/tests/conftest.py
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from app.common.database import get_session
from app.main import create_app

# Use SQLite for tests (no external DB needed)
TEST_DATABASE_URL = "sqlite+aiosqlite:///test.db"


@pytest.fixture
async def app():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    test_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    application = create_app()

    async def override_get_session():
        async with test_session() as session:
            yield session

    application.dependency_overrides[get_session] = override_get_session

    yield application

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
```

Note: add `aiosqlite` to dev dependencies in pyproject.toml.

**Step 4: Implement auth router**

```python
# backend/app/auth/router.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.schemas import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.auth.service import create_access_token, create_refresh_token, hash_password, verify_password
from app.common.database import get_session

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(request: RegisterRequest, session: AsyncSession = Depends(get_session)):
    # Check if email already exists
    result = await session.execute(select(User).where(User.email == request.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=request.email,
        name=request.name,
        password_hash=hash_password(request.password),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return UserResponse(id=user.id, email=user.email, name=user.name, role=user.role.value, is_active=user.is_active)


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return TokenResponse(
        access_token=create_access_token(user.id, user.role.value),
        refresh_token=create_refresh_token(user.id),
    )
```

**Step 5: Register router in main.py**

```python
# Add to backend/app/main.py create_app():
from app.auth.router import router as auth_router
app.include_router(auth_router)
```

**Step 6: Run tests — expect PASS**

```bash
cd backend && uv run pytest tests/test_auth_api.py -v
```

**Step 7: Commit**

```bash
git add backend/
git commit -m "feat: add auth API (register, login) with JWT tokens"
```

---

### Task 1.6: Auth Dependencies (Current User, Require Auth)

**Files:**
- Create: `backend/app/dependencies.py`
- Modify: `backend/tests/test_auth_api.py`

**Step 1: Write failing test**

```python
# Add to backend/tests/test_auth_api.py

@pytest.mark.asyncio
async def test_get_current_user(client):
    # Register and login
    await client.post("/api/v1/auth/register", json={
        "email": "me@test.com",
        "name": "Me",
        "password": "pass123",
    })
    login_resp = await client.post("/api/v1/auth/login", json={
        "email": "me@test.com",
        "password": "pass123",
    })
    token = login_resp.json()["access_token"]

    # Get current user
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["email"] == "me@test.com"


@pytest.mark.asyncio
async def test_protected_route_without_token(client):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
```

**Step 2: Implement dependencies**

```python
# backend/app/dependencies.py
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.service import decode_token
from app.common.database import get_session

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session: AsyncSession = Depends(get_session),
) -> User:
    payload = decode_token(credentials.credentials)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = await session.get(User, payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user
```

**Step 3: Add /me endpoint to auth router**

```python
# Add to backend/app/auth/router.py

from app.dependencies import get_current_user

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        name=current_user.name,
        role=current_user.role.value,
        is_active=current_user.is_active,
    )
```

**Step 4: Run tests — expect PASS**

```bash
cd backend && uv run pytest tests/test_auth_api.py -v
```

**Step 5: Commit**

```bash
git add backend/app/dependencies.py backend/app/auth/router.py backend/tests/test_auth_api.py
git commit -m "feat: add auth dependencies (get_current_user) and /me endpoint"
```

---

### Task 1.7: Frontend Auth Pages (Login + Register)

**Files:**
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/auth/AuthProvider.tsx`
- Create: `frontend/src/auth/LoginPage.tsx`
- Create: `frontend/src/auth/RegisterPage.tsx`
- Modify: `frontend/src/App.tsx`

**Step 1: Create API client**

```typescript
// frontend/src/api/client.ts
const API_BASE = "/api/v1";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = localStorage.getItem("access_token");
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(error.detail || `HTTP ${res.status}`);
  }

  return res.json();
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) }),
};
```

**Step 2: Create AuthProvider**

```typescript
// frontend/src/auth/AuthProvider.tsx
import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { api } from "../api/client";

interface User {
  id: string;
  email: string;
  name: string;
  role: string;
}

interface AuthContextType {
  user: User | null;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, name: string, password: string) => Promise<void>;
  logout: () => void;
  isLoading: boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (token) {
      api.get<User>("/auth/me").then(setUser).catch(() => {
        localStorage.removeItem("access_token");
        localStorage.removeItem("refresh_token");
      }).finally(() => setIsLoading(false));
    } else {
      setIsLoading(false);
    }
  }, []);

  const login = async (email: string, password: string) => {
    const tokens = await api.post<{ access_token: string; refresh_token: string }>(
      "/auth/login", { email, password }
    );
    localStorage.setItem("access_token", tokens.access_token);
    localStorage.setItem("refresh_token", tokens.refresh_token);
    const me = await api.get<User>("/auth/me");
    setUser(me);
  };

  const register = async (email: string, name: string, password: string) => {
    await api.post("/auth/register", { email, name, password });
    await login(email, password);
  };

  const logout = () => {
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, login, register, logout, isLoading }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
```

**Step 3: Create Login and Register pages** (using shadcn components)

Create `frontend/src/auth/LoginPage.tsx` and `frontend/src/auth/RegisterPage.tsx` using shadcn/ui `Card`, `Input`, `Button`, `Label` components with form handling that calls `useAuth().login()` and `useAuth().register()`.

**Step 4: Update App.tsx routing**

```typescript
// frontend/src/App.tsx - add routes:
import { AuthProvider } from "./auth/AuthProvider";
import { LoginPage } from "./auth/LoginPage";
import { RegisterPage } from "./auth/RegisterPage";

// Wrap everything in <AuthProvider>, add routes:
// <Route path="/login" element={<LoginPage />} />
// <Route path="/register" element={<RegisterPage />} />
```

**Step 5: Verify manually**

```bash
cd frontend && npm run dev
```

Visit `http://localhost:5173/login` and `http://localhost:5173/register`.

**Step 6: Commit**

```bash
git add frontend/src/
git commit -m "feat: add frontend auth (login, register, AuthProvider)"
```

---

## Phase 2: Project Management + Multi-Tenancy

> Detailed tasks to be expanded when Phase 1 is complete.

### Task 2.1: Project Model + Migration
- Create `backend/app/projects/models.py` with `Project` and `ProjectMember` tables
- `project_id` scoping on all queries
- Alembic migration

### Task 2.2: Project CRUD Router
- `POST /api/v1/projects` — create project
- `GET /api/v1/projects` — list user's projects
- `GET /api/v1/projects/{id}` — get project details
- `PUT /api/v1/projects/{id}` — update project
- `DELETE /api/v1/projects/{id}` — soft delete

### Task 2.3: Project Membership
- `POST /api/v1/projects/{id}/members` — add member with role
- `GET /api/v1/projects/{id}/members` — list members
- `DELETE /api/v1/projects/{id}/members/{user_id}` — remove member

### Task 2.4: Permission Middleware
- `require_project_role(min_role)` dependency
- Checks user's membership + role for the project in URL

### Task 2.5: Frontend — Project List + Create
- Project dashboard (list all user's projects)
- Create project modal/page
- Project layout with sidebar nav

---

## Phase 3: Data Connectors + Ingestion

### Task 3.1: Connector Base ABC
- `backend/app/connectors/base.py` — `ConnectorBase` with `connect`, `preview`, `fetch`, `validate_config`
- `backend/app/connectors/registry.py` — connector type registry

### Task 3.2: File Upload Connector
- Upload to S3, parse CSV/Excel/JSON/Parquet
- Chunked ingestion (1000-row batches)
- `DataSource` model + migration

### Task 3.3: Databricks Connector
- Databricks SQL warehouse connection via `databricks-sql-connector`
- Table/view listing, preview, batch fetch

### Task 3.4: Ingestion Pipeline
- Background worker task: fetch from connector → parse → insert patients + notes into PostgreSQL
- Progress tracking via Redis

### Task 3.5: Frontend — Data Source Config + Upload UI
- Connector wizard (select type → configure → preview → import)
- Drag-and-drop file upload
- Ingestion progress bar (polling)

---

## Phase 4: Predictor System

### Task 4.1: Base Predictor Interface
- Port `backend/app/predictors/base.py` from current codebase
- `PredictionResult` dataclass, `BasePredictor` ABC

### Task 4.2: LLM Predictor
- Port `backend/app/predictors/llm.py` — LiteLLM integration
- Prompt injection protection, retry logic
- `PredictorConfig` model + migration

### Task 4.3: PINES Predictor
- Port `backend/app/predictors/pines.py` — HTTP client to PINES service
- Score normalization, batch support

### Task 4.4: Predictor Factory + Config API
- `GET/POST /api/v1/projects/{id}/predictors` — CRUD predictor configs
- Factory pattern: config → predictor instance

### Task 4.5: Frontend — Predictor Configuration
- LLM setup form (provider, model, API key env, event definition)
- PINES setup form (URL, model version)
- Test prediction button

---

## Phase 5: NLP Pipeline

### Task 5.1: spaCy Preprocessing Service
- Sentence splitting, tokenization, regex matching, negation detection
- Port from `cedars/app/nlpprocessor.py`

### Task 5.2: Search Query Config
- Regex pattern management per project
- `SearchQuery` model + API

### Task 5.3: NLP Background Worker
- Process patient notes: tokenize → match → mark candidates
- Progress tracking

### Task 5.4: Frontend — Pipeline Config + Status
- Regex pattern builder UI
- NLP job progress tracking

---

## Phase 6: Annotations + Adjudication UI

### Task 6.1: Annotation Models
- `Sentence`, `Prediction`, `Annotation` tables
- Patient locking (DB-backed, not session)

### Task 6.2: Adjudication API
- `GET /api/v1/projects/{id}/annotations/next` — next sentence to review
- `POST /api/v1/projects/{id}/annotations/{id}` — submit judgment
- `POST /api/v1/projects/{id}/patients/{id}/lock` — lock patient
- Auto-adjudication: apply threshold from active predictor

### Task 6.3: Frontend — Annotation UI
- The core annotation page (see wireframe in design doc)
- Keyboard shortcuts: Y/N/S for judgment, J/K for navigation
- Patient timeline, surrounding context
- LLM reasoning display
- Progress bar

### Task 6.4: WebSocket — Live Updates
- Job progress notifications
- Patient lock/unlock events
- Annotation progress updates

---

## Phase 7: Unified Evaluation Framework

### Task 7.1: Evaluation Models + Migration
- `EvaluationSession`, `EvaluationJudgment`, `ValidatedPredictor` tables
- `predictor_config_id` FK (works for ANY predictor type)

### Task 7.2: Sampling Service
- Stratified keyword-based sampling (port from current)
- Works against PostgreSQL notes table

### Task 7.3: Prediction Runner
- Background job: run `predictor.predict()` for each sampled note
- Uses same `BasePredictor` interface — works for LLM and PINES identically

### Task 7.4: Human Review API
- `GET /next` — next unjudged item
- `POST /judge` — record judgment (correct/wrong/skip)
- Recompute metrics after each judgment

### Task 7.5: Metrics Computation
- Accuracy, precision, recall, F1
- Threshold curve: metrics at different threshold values

### Task 7.6: Validation + Activation
- `POST /validate` — snapshot config + metrics + threshold
- `POST /activate` — set as active predictor for project
- Only one active per project

### Task 7.7: Comparison View
- Run multiple sessions on same sample
- Side-by-side metrics table
- Disagreement analysis

### Task 7.8: Frontend — Evaluation UI
- Sampling config form
- Review page (note + prediction + judgment buttons)
- Metrics dashboard with charts
- Comparison table
- Threshold slider

---

## Phase 8: Learning Loops + Training Data Export

### Task 8.1: Few-Shot Example Bank
- `PredictorExample` model — stores corrected examples
- API to manage examples (add from evaluation, toggle active)
- LLM predictor includes active examples in prompt

### Task 8.2: Error Pattern Analysis
- Cluster wrong predictions by type (FP vs FN)
- Surface common patterns in the UI

### Task 8.3: Training Data Export
- Export evaluation judgments in HuggingFace formats:
  - DPO pairs (chosen/rejected)
  - KTO binary (completion + desirable/undesirable)
  - SFT (prompt + correct completion)
- `GET /api/v1/projects/{id}/evaluation/export-training-data`

### Task 8.4: Prompt Iteration Tracking
- `PromptIteration` model — tracks parent config, change description, before/after metrics
- UI to compare prompt versions

### Task 8.5: Uncertainty Sampling for Review Queue
- Sort annotation queue by prediction uncertainty (|score - 0.5|)
- Disagreement sampling when both LLM and PINES are configured

---

## Phase 9: Export + Monitoring

### Task 9.1: Data Export
- CSV, Parquet, JSON export of annotations + predictions
- `GET /api/v1/projects/{id}/export`
- Background job for large exports → S3 → download link

### Task 9.2: Audit Log
- Append-only `audit_log` table
- Middleware to log all PHI access and admin actions
- Admin UI to view audit trail

### Task 9.3: Prometheus Metrics
- Request latency, queue depth, prediction counts
- `/metrics` endpoint with prometheus-client

### Task 9.4: LLM Cost Tracking
- Track cost per LLM prediction (from LiteLLM response)
- Per-project budget limits
- Dashboard showing spend

---

## Phase 10: MongoDB Migration Tool

### Task 10.1: Migration Script
- `backend/migrations/mongo_to_postgres.py`
- Read from MongoDB → transform → insert into PostgreSQL
- Per-collection mapping (INFO → projects, NOTES → notes, etc.)

### Task 10.2: Data Validation
- Row count comparison
- Spot-check data integrity
- Run evaluation on migrated data to verify correctness

---

## Phase 11: Remove Flask App

### Task 11.1: Verify Feature Parity
- Checklist of all Flask routes mapped to FastAPI equivalents
- Manual QA pass

### Task 11.2: Update Docker Compose
- Remove Flask/Gunicorn services from docker-compose.yml
- Update nginx config to point to new backend
- Merge docker-compose.v2.yml into docker-compose.yml

### Task 11.3: Update Documentation
- Update CLAUDE.md with new build commands
- Update README
- Archive old Flask code

---

## Running the Tests

### Backend

```bash
cd backend
uv sync --group dev
uv run pytest -v                          # All tests
uv run pytest tests/test_auth.py -v       # Single file
uv run pytest -k "test_login" -v          # By name
uv run pytest --cov=app                   # With coverage
```

### Frontend

```bash
cd frontend
npm test                                  # Unit tests
npx playwright test                       # E2E tests (added later)
```

### Integration (Docker)

```bash
docker compose -f docker-compose.v2.yml up -d   # Start services
cd backend && uv run pytest -v                    # Run against real DB
docker compose -f docker-compose.v2.yml down      # Cleanup
```
