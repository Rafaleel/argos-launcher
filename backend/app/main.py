from fastapi import FastAPI
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.api import router

app = FastAPI(title="Argos Launcher")
# No CORS middleware: the UI reaches the API through the Vite proxy. Host
# checking blocks DNS-rebinding, since the API can start programs.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])
app.include_router(router)

# Run with: uvicorn app.main:app --host 127.0.0.1
