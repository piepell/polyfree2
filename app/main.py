"""
Main FastAPI Application
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.routes import router as api_router
from app.services.pipeline import job_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Starting Photogrammetry Backend...")
    print(f"Upload dir: {settings.UPLOAD_DIR}")
    print(f"Output dir: {settings.OUTPUT_DIR}")
    print(f"Temp dir: {settings.TEMP_DIR}")

    # Start job workers
    await job_manager.start_workers(num_workers=1)
    print("Job workers started")

    yield

    # Shutdown
    print("Shutting down...")
    await job_manager.stop_workers()
    print("Job workers stopped")


app = FastAPI(
    title="Photogrammetry Backend",
    description="Cloud photogrammetry API: Upload photos → Get 3D models (STL, OBJ, GLTF)",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS for Android app and Web Preview
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for testing - restrict in production
    allow_credentials=False,  # Must be False when allow_origins=["*"]
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(api_router, prefix="/api")


@app.get("/")
async def root():
    return {
        "name": "Photogrammetry Backend",
        "version": "1.0.0",
        "description": "Upload photos → Get 3D models",
        "docs": "/docs",
        "health": "/api/health",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        workers=settings.WORKERS,
        reload=True,
    )