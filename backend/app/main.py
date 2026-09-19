from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from app.auth import Sessions, require_signed_in
from app.auth import router as session_router
from app.chance import Dice
from app.child import router as child_router
from app.clock import SystemClock
from app.config import Settings
from app.db import create_session_factory
from app.diary import router as diary_router
from app.health import router as health_router
from app.parents import router as parents_router
from app.push import router as push_router
from app.sitting import router as sitting_router
from app.vapid import configured_vapid


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API. Tests call this with their own settings; production uses the default."""
    settings = settings or Settings()

    app = FastAPI(title="Kidiary")
    app.state.settings = settings
    app.state.session_factory = create_session_factory(settings.database_url)
    app.state.clock = SystemClock(settings.timezone)
    app.state.chance = Dice()
    app.state.sessions = Sessions(settings.session_secret, secure=settings.cookie_secure)
    # Nothing if this stack has no keys, which is a stack that cannot send the
    # evening notification but runs. A malformed pair raises here, before it serves.
    app.state.vapid = configured_vapid(settings)

    # The PIN exchange is the only door open to a device that has not been signed in.
    # The rest of this router — reading the session, and saying which Parent this
    # device is — carries its own guard, because it is reached only after the PIN.
    app.include_router(session_router, prefix="/api")

    # Everything else is behind the PIN. Mounting the guard here rather than on each
    # route means a new router is only reachable once someone has said so out loud.
    signed_in = [Depends(require_signed_in)]
    app.include_router(health_router, prefix="/api", dependencies=signed_in)
    app.include_router(child_router, prefix="/api", dependencies=signed_in)
    app.include_router(parents_router, prefix="/api", dependencies=signed_in)
    app.include_router(diary_router, prefix="/api", dependencies=signed_in)
    app.include_router(sitting_router, prefix="/api", dependencies=signed_in)
    app.include_router(push_router, prefix="/api", dependencies=signed_in)

    # Mounted last so that /api keeps precedence. In local development this
    # directory does not exist and Vite serves the frontend on its own port.
    # The PIN screen is part of this bundle, so the bundle itself is not behind the
    # PIN; it holds nothing about the Child until the API answers it.
    if settings.static_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="web")

    return app


app = create_app()
