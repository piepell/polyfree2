"""
Main FastAPI Application
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import structlog

from app.core.config import settings
from app.core.database import init_db
from app.api.routes import router as api_router
from app.services.pipeline import job_manager

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

# Prometheus metrics
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"]
)
JOBS_CREATED = Counter("jobs_created_total", "Total jobs created")
JOBS_COMPLETED = Counter("jobs_completed_total", "Total jobs completed")
JOBS_FAILED = Counter("jobs_failed_total", "Total jobs failed")

# Rate limiter
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger = structlog.get_logger("startup")
    logger.info("Starting Photogrammetry Backend",
                upload_dir=settings.UPLOAD_DIR,
                output_dir=settings.OUTPUT_DIR,
                temp_dir=settings.TEMP_DIR,
                workers=settings.WORKERS)

    # Initialize database
    await init_db()

    # Start job workers
    await job_manager.start_workers()
    logger.info("Job workers started")

    yield

    # Shutdown
    logger.info("Shutting down...")
    await job_manager.stop_workers()
    logger.info("Job workers stopped")


app = FastAPI(
    title="Photogrammetry Backend",
    description="Cloud photogrammetry API: Upload photos → Get 3D models (STL, OBJ, GLTF)",
    version="1.0.0",
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS for Android app and Web Preview
origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins else ["*"],
    allow_credentials=True if origins and "*" not in origins else False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics middleware
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start_time = asyncio.get_event_loop().time()
    response = await call_next(request)
    duration = asyncio.get_event_loop().time() - start_time
    
    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=request.url.path,
        status=response.status_code
    ).inc()
    REQUEST_LATENCY.labels(
        method=request.method,
        endpoint=request.url.path
    ).observe(duration)
    
    return response


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


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """Prometheus metrics endpoint"""
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        workers=settings.WORKERS,
        reload=False,
        log_config=None,  # Use structlog instead
    )