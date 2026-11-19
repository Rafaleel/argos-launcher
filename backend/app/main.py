from urllib.parse import urlparse

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.api import router
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
# No CORS middleware: the UI reaches the API through the Vite proxy. Host
# checking blocks DNS-rebinding, since the API can start programs.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])
app.include_router(router)

# Run with: uvicorn app.main:app --host 127.0.0.1


@app.middleware("http")
async def reject_foreign_origin(request: Request, call_next):
    # Cross-site pages can send simple POSTs without a CORS preflight. Browsers
    # always attach Origin to them, so refuse any Origin that is not local.
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD", "OPTIONS") and origin is not None:
        if urlparse(origin).hostname not in ("localhost", "127.0.0.1"):
            return JSONResponse({"detail": "Foreign origin"}, status_code=403)
    return await call_next(request)
