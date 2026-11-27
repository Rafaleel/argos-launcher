from urllib.parse import urlparse

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.api import router
from app.api_dolphin import router as dolphin_router
from app.api_progress import router as progress_router
from app.api_ra import router as ra_router
from app.db import connect
from app.sessions.tracker import close_orphans

@asynccontextmanager
async def lifespan(_: FastAPI):
    # A crash can leave sessions open; close them at their last heartbeat.
    conn = connect()
    close_orphans(conn)
    conn.close()
    yield


app = FastAPI(title="Argos Launcher", lifespan=lifespan)
# In the browser the UI reaches the API through the Vite proxy (same origin). The desktop app
# loads the UI from Tauri's own origin, so only that origin gets CORS. Host checking blocks
# DNS-rebinding, since the API can start programs.
TAURI_ORIGINS = ["tauri://localhost", "http://tauri.localhost"]
app.add_middleware(CORSMiddleware, allow_origins=TAURI_ORIGINS, allow_methods=["*"], allow_headers=["Content-Type"])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])
app.include_router(router)
app.include_router(dolphin_router)
app.include_router(ra_router)
app.include_router(progress_router)

# Run with: uvicorn app.main:app --host 127.0.0.1 --port 8765 (the desktop app starts it itself)


@app.middleware("http")
async def reject_foreign_origin(request: Request, call_next):
    # Cross-site pages can send simple POSTs without a CORS preflight. Browsers
    # always attach Origin to them, so refuse any Origin that is not local.
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD", "OPTIONS") and origin is not None:
        if origin not in TAURI_ORIGINS and urlparse(origin).hostname not in ("localhost", "127.0.0.1"):
            return JSONResponse({"detail": "Foreign origin"}, status_code=403)
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    # FastAPI echoes the rejected input by default; the RetroAchievements key travels in a body.
    errors = [{k: e[k] for k in ("loc", "msg", "type") if k in e} for e in exc.errors()]
    return JSONResponse({"detail": errors}, status_code=422)
