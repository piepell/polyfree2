"""
Photogrammetry Models
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
import uuid
from datetime import datetime


class ReconstructionQuality(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ReconstructionType(str, Enum):
    MESH = "mesh"           # Traditional photogrammetry mesh
    GAUSSIAN_SPLATTING = "3dgs"  # 3D Gaussian Splatting
    NERF = "nerf"           # Neural Radiance Fields


class OutputFormat(str, Enum):
    STL = "stl"
    OBJ = "obj"
    GLTF = "gltf"
    GLB = "glb"
    PLY = "ply"


class JobStatus(str, Enum):
    PENDING = "pending"
    UPLOADING = "uploading"
    QUEUED = "queued"
    PROCESSING = "processing"
    SFM = "sfm"              # Structure from Motion
    MVS = "mvs"              # Multi-View Stereo
    MESHING = "meshing"
    TEXTURING = "texturing"
    EXPORTING = "exporting"
    COMPLETED = "completed"
    FAILED = "failed"


class JobCreate(BaseModel):
    quality: ReconstructionQuality = ReconstructionQuality.HIGH
    reconstruction_type: ReconstructionType = ReconstructionType.MESH
    output_formats: List[OutputFormat] = [OutputFormat.STL, OutputFormat.OBJ, OutputFormat.GLTF]
    texture: bool = True
    max_faces: Optional[int] = 500000  # For mesh simplification
    scale: Optional[float] = None      # Known scale factor (meters per unit)


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    message: str
    progress: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    progress: float
    message: str
    current_step: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    result_files: Dict[str, str] = {}  # format -> download URL
    stats: Dict[str, Any] = {}


class UploadResponse(BaseModel):
    upload_id: str
    upload_url: str
    expires_in: int = 3600


class HealthResponse(BaseModel):
    status: str
    version: str
    gpu_available: bool
    colmap_version: Optional[str] = None
    active_jobs: int
    queue_length: int