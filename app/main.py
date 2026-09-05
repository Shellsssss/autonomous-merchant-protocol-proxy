from fastapi import FastAPI
from app.api.manifest import router as manifest_router
from app.api.negotiate import router as negotiate_router
from app.config import get_settings
from app.api.catalog import router as catalog_router
from app.api.settle import router as settle_router
from fastapi.middleware.cors import CORSMiddleware

def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description=(
            "Autonomous Merchant Protocol Proxy — "
            "security-first gateway for agentic commerce."
        ),
        version=settings.app_version,
        debug=settings.debug,
    )

    app.include_router(manifest_router)
    app.include_router(negotiate_router)
    app.include_router(catalog_router)
    app.include_router(settle_router)

    @app.get("/health")
    async def health_check():
        return {
            "status": "ok",
            "service": settings.app_name,
            "version": settings.app_version,
            "environment": settings.environment,
        }
    
    return app

app = create_app()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)