"""
Photogrammetry Backend Configuration
"""
from pydantic_settings import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 1

    # Auth
    SECRET_KEY: str = "dev-secret-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # Processing
    MAX_IMAGES: int = 200
    MAX_IMAGE_SIZE_MB: int = 50
    COLMAP_QUALITY: str = "high"
    USE_GPU: bool = True
    GPU_DEVICE: int = 0

    # Paths
    UPLOAD_DIR: str = "/data/uploads"
    OUTPUT_DIR: str = "/data/outputs"
    TEMP_DIR: str = "/tmp/photogrammetry"
    COLMAP_PATH: str = "colmap"

    # Quality presets
    QUALITY_LOW_MAX_IMAGES: int = 50
    QUALITY_LOW_IMAGE_SIZE: int = 1024
    QUALITY_MEDIUM_MAX_IMAGES: int = 100
    QUALITY_MEDIUM_IMAGE_SIZE: int = 2048
    QUALITY_HIGH_MAX_IMAGES: int = 200
    QUALITY_HIGH_IMAGE_SIZE: int = 4096

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()

# Ensure directories exist
for path in [settings.UPLOAD_DIR, settings.OUTPUT_DIR, settings.TEMP_DIR]:
    os.makedirs(path, exist_ok=True)

# Quality presets
QUALITY_PRESETS = {
    "low": {
        "max_images": settings.QUALITY_LOW_MAX_IMAGES,
        "max_image_size": settings.QUALITY_LOW_IMAGE_SIZE,
        "colmap_options": "--SiftExtraction.max_num_features 8192 --SiftMatching.max_num_matches 16384",
    },
    "medium": {
        "max_images": settings.QUALITY_MEDIUM_MAX_IMAGES,
        "max_image_size": settings.QUALITY_MEDIUM_IMAGE_SIZE,
        "colmap_options": "--SiftExtraction.max_num_features 16384 --SiftMatching.max_num_matches 32768",
    },
    "high": {
        "max_images": settings.QUALITY_HIGH_MAX_IMAGES,
        "max_image_size": settings.QUALITY_HIGH_IMAGE_SIZE,
        "colmap_options": "--SiftExtraction.max_num_features 32768 --SiftMatching.max_num_matches 65536",
    },
}