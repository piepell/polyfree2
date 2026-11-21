"""
Updated API Routes with Authentication and Engine Integration
"""
import asyncio
import os
import shutil
import uuid
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, BackgroundTasks, Query, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBearer
from pydantic import BaseModel

from app.core.config import settings
from app.core.security import (
    create_access_token, verify_token, get_current_user, require_auth,
    verify_api_key, api_key_manager
)
from app.models.schemas import (
    JobCreate, JobResponse, JobStatusResponse, UploadResponse,
    HealthResponse, JobStatus, OutputFormat, ReconstructionQuality, ReconstructionType
)
from app.services.pipeline import job_manager
from app.services.engine import get_engine_service, PolyFreeEngineService
from app.services.file_service import get_file_service, FileService

router = APIRouter()
security = HTTPBearer(auto_error=False)


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint - public for monitoring"""
    # Check COLMAP or pycolmap
    colmap_version = None
    try:
        import pycolmap
        colmap_version = f"pycolmap {getattr(pycolmap, '__version__', 'available')}"
    except ImportError:
        try:
            result = await asyncio.create_subprocess_exec(
                settings.COLMAP_PATH, "--version",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await result.communicate()
            if result.returncode == 0:
                colmap_version = stdout.decode().strip()
        except Exception:
            pass

    # Check GPU
    gpu_available = False
    try:
        import torch
        gpu_available = torch.cuda.is_available()
    except Exception:
        pass

    # Check PolyFree engine
    engine = await get_engine_service()
    polyfree_available = engine.available

    return HealthResponse(
        status="healthy",
        version="1.0.0",
        gpu_available=gpu_available,
        colmap_version=colmap_version,
        active_jobs=sum(1 for j in job_manager.jobs.values() if j["status"] == JobStatus.PROCESSING),
        queue_length=job_manager.queue.qsize(),
    )


# ========================================================================
# Authentication Endpoints
# ========================================================================

class TokenRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class APIKeyCreate(BaseModel):
    name: str
    permissions: Optional[List[str]] = None


class APIKeyResponse(BaseModel):
    api_key: str
    name: str
    permissions: List[str]
    created_at: datetime


@router.post("/auth/token", response_model=TokenResponse)
async def create_token(token_request: TokenRequest):
    """Create access token with configurable credentials"""
    username_valid = token_request.username == settings.ADMIN_USERNAME
    password_valid = False
    
    if settings.ADMIN_PASSWORD_HASH:
        from app.core.security import verify_password
        password_valid = verify_password(token_request.password, settings.ADMIN_PASSWORD_HASH)
    else:
        password_valid = (token_request.password == settings.ADMIN_PASSWORD)
    
    if username_valid and password_valid:
        token = create_access_token(
            data={"sub": token_request.username, "roles": ["admin"]},
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        return TokenResponse(
            access_token=token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        )
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/auth/api-keys", response_model=APIKeyResponse)
async def create_api_key(
    key_data: APIKeyCreate,
    user: Dict[str, Any] = Depends(require_auth),
):
    """Create new API key (requires authentication)"""
    api_key = api_key_manager.generate_key(key_data.name, key_data.permissions)
    key_info = api_key_manager.api_keys[api_key]
    
    return APIKeyResponse(
        api_key=api_key,
        name=key_info["name"],
        permissions=key_info["permissions"],
        created_at=key_info["created_at"],
    )


@router.get("/auth/api-keys")
async def list_api_keys(user: Dict[str, Any] = Depends(require_auth)):
    """List API keys"""
    return [
        {
            "name": info["name"],
            "permissions": info["permissions"],
            "created_at": info["created_at"],
            "active": info["active"],
        }
        for key, info in api_key_manager.api_keys.items()
    ]


@router.delete("/auth/api-keys/{key_prefix}")
async def revoke_api_key(
    key_prefix: str,
    user: Dict[str, Any] = Depends(require_auth),
):
    """Revoke API key by prefix"""
    # Find key by prefix
    for key in list(api_key_manager.api_keys.keys()):
        if key.startswith(key_prefix):
            api_key_manager.revoke_key(key)
            return {"message": f"Key {key_prefix} revoked"}
    
    raise HTTPException(status_code=404, detail="API key not found")


# ========================================================================
# Job Management Endpoints
# ========================================================================

@router.post("/jobs", response_model=JobResponse)
async def create_job(
    job_data: JobCreate,
    user: Optional[Dict[str, Any]] = Depends(get_current_user),
):
    """Create a new photogrammetry job"""
    job_id = await job_manager.create_job(
        quality=job_data.quality,
        reconstruction_type=job_data.reconstruction_type,
        output_formats=job_data.output_formats,
        texture=job_data.texture,
        max_faces=job_data.max_faces,
        scale=job_data.scale,
    )
    return JobResponse(
        job_id=job_id,
        status=JobStatus.PENDING,
        message="Job created. Upload images to proceed.",
        progress=0.0,
    )


@router.post("/jobs/{job_id}/upload", response_model=UploadResponse)
async def upload_images(
    job_id: str,
    files: List[UploadFile] = File(...),
    user: Optional[Dict[str, Any]] = Depends(get_current_user),
    file_service: FileService = Depends(get_file_service),
):
    """Upload images for a job"""
    job = await job_manager.get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] not in [JobStatus.PENDING, JobStatus.UPLOADING]:
        raise HTTPException(status_code=400, detail=f"Job is in {job['status']} state, cannot upload")

    # Save files using file service
    saved_paths = await file_service.save_upload(job_id, files)

    if len(saved_paths) + len(job.get("image_paths", [])) > settings.MAX_IMAGES:
        # Clean up excess
        for p in saved_paths:
            p.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Too many images. Max: {settings.MAX_IMAGES}")

    # Update job
    existing = job.get("image_paths", [])
    job["image_paths"] = existing + [str(p) for p in saved_paths]
    job["status"] = JobStatus.UPLOADING

    return UploadResponse(
        upload_id=job_id,
        upload_url=f"/api/jobs/{job_id}/status",
        expires_in=3600,
    )


@router.post("/jobs/{job_id}/start")
async def start_job(
    job_id: str,
    user: Optional[Dict[str, Any]] = Depends(get_current_user),
):
    """Start processing a job (move from UPLOADING to QUEUED)"""
    job = await job_manager.get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] not in [JobStatus.PENDING, JobStatus.UPLOADING]:
        raise HTTPException(status_code=400, detail=f"Job is in {job['status']} state")

    if not job.get("image_paths"):
        raise HTTPException(status_code=400, detail="No images uploaded")

    job["status"] = JobStatus.QUEUED
    job["message"] = "Job queued for processing"
    
    return {"message": "Job queued", "job_id": job_id}


@router.get("/jobs/{job_id}/status", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    user: Optional[Dict[str, Any]] = Depends(get_current_user),
    file_service: FileService = Depends(get_file_service),
):
    """Get job status with result download URLs"""
    job = await job_manager.get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Get result files from file service
    result_files = file_service.get_all_results(job_id)
    result_urls = {fmt: f"/api/jobs/{job_id}/download/{fmt}" for fmt in result_files.keys()}

    return JobStatusResponse(
        job_id=job_id,
        status=job["status"],
        progress=job["progress"],
        message=job["message"],
        current_step=job.get("current_step"),
        started_at=datetime.fromtimestamp(job["started_at"]) if job.get("started_at") else None,
        completed_at=datetime.fromtimestamp(job["completed_at"]) if job.get("completed_at") else None,
        error=job.get("error"),
        result_files=result_urls,
        stats=job.get("stats", {}),
    )


@router.get("/jobs/{job_id}/download/{format}")
async def download_result(
    job_id: str,
    format: str,
    user: Optional[Dict[str, Any]] = Depends(get_current_user),
    file_service: FileService = Depends(get_file_service),
):
    """Download result file"""
    job = await job_manager.get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != JobStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Job not completed")

    file_path = file_service.get_result_file(job_id, format)
    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found for format: {format}")

    return FileResponse(
        path=str(file_path),
        filename=f"model_{job_id}.{format}",
        media_type="application/octet-stream"
    )


@router.get("/jobs/{job_id}/package")
async def download_package(
    job_id: str,
    format: str = Query("zip", regex="^(zip|tar\\.gz)$"),
    user: Optional[Dict[str, Any]] = Depends(get_current_user),
    file_service: FileService = Depends(get_file_service),
):
    """Download all results as a package"""
    job = await job_manager.get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != JobStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Job not completed")

    package_path = await file_service.create_job_package(job_id, format)
    if not package_path:
        raise HTTPException(status_code=404, detail="No results to package")

    return FileResponse(
        path=str(package_path),
        filename=f"results_{job_id}.{format}",
        media_type="application/zip" if format == "zip" else "application/gzip"
    )


@router.delete("/jobs/{job_id}")
async def delete_job(
    job_id: str,
    keep_outputs: bool = Query(False),
    user: Optional[Dict[str, Any]] = Depends(get_current_user),
    file_service: FileService = Depends(get_file_service),
):
    """Delete a job and its files"""
    job = await job_manager.get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Clean up files
    await file_service.cleanup_job(job_id, keep_outputs=keep_outputs)

    # Remove from memory
    if job_id in job_manager.jobs:
        del job_manager.jobs[job_id]

    return {"message": "Job deleted"}


@router.get("/jobs")
async def list_jobs(
    status_filter: Optional[JobStatus] = Query(None, alias="status"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    user: Optional[Dict[str, Any]] = Depends(get_current_user),
):
    """List all jobs with optional filtering"""
    jobs_list = list(job_manager.jobs.values())
    
    if status_filter:
        jobs_list = [j for j in jobs_list if j["status"] == status_filter]
    
    # Sort by created_at descending
    jobs_list.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    
    # Apply pagination
    jobs_list = jobs_list[offset:offset + limit]
    
    return [
        {
            "job_id": j["job_id"],
            "status": j["status"],
            "progress": j["progress"],
            "created_at": datetime.fromtimestamp(j["created_at"]) if j.get("created_at") else None,
        }
        for j in jobs_list
    ]


# ========================================================================
# Engine Management Endpoints
# ========================================================================

class EngineConfig(BaseModel):
    engine_path: Optional[str] = None
    library_path: Optional[str] = None


@router.get("/engine/status")
async def engine_status(
    engine_service: PolyFreeEngineService = Depends(get_engine_service),
):
    """Get engine status and capabilities - public for testing"""
    is_avail = engine_service.available
    return {
        "available": is_avail,
        "engine_path": engine_service.engine_path,
        "library_path": engine_service.library_path,
        "capabilities": {
            "sfm": is_avail,
            "mvs": is_avail,
            "meshing": is_avail,
            "texturing": is_avail,
            "export_formats": ["stl", "obj", "gltf", "glb", "ply"] if is_avail else [],
            "reconstruction_types": ["mesh"],
            "quality_presets": ["low", "medium", "high"],
        },
    }


@router.post("/engine/configure")
async def configure_engine(
    config: EngineConfig,
    user: Dict[str, Any] = Depends(require_auth),
    engine_service: PolyFreeEngineService = Depends(get_engine_service),
):
    """Configure engine paths (admin only)"""
    if config.engine_path:
        engine_service.engine_path = config.engine_path
    if config.library_path:
        engine_service.library_path = config.library_path
    
    engine_service.available = engine_service._check_availability()
    
    return {
        "message": "Engine configuration updated",
        "available": engine_service.available,
        "engine_path": engine_service.engine_path,
        "library_path": engine_service.library_path,
    }


# ========================================================================
# System Management Endpoints
# ========================================================================

@router.get("/system/disk")
async def disk_usage(
    user: Dict[str, Any] = Depends(require_auth),
    file_service: FileService = Depends(get_file_service),
):
    """Get disk usage statistics"""
    return file_service.get_disk_usage()


@router.post("/system/cleanup")
async def cleanup_system(
    max_age_hours: int = Query(24, ge=1),
    dry_run: bool = Query(False),
    user: Dict[str, Any] = Depends(require_auth),
    file_service: FileService = Depends(get_file_service),
):
    """Clean up old job files"""
    return await file_service.cleanup_old_jobs(max_age_hours, dry_run)


@router.get("/system/info")
async def system_info():
    """Get system information"""
    import platform
    import psutil
    
    return {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "cpu_count": psutil.cpu_count(),
        "memory_total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
        "memory_available_gb": round(psutil.virtual_memory().available / (1024**3), 2),
        "disk_usage": str(psutil.disk_usage("/")),
    }