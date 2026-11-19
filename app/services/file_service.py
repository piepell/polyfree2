"""
File Management Service for Photogrammetry Backend
Handles uploads, outputs, temporary files, and cleanup
"""
import asyncio
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from fastapi import UploadFile
from app.core.config import settings

logger = logging.getLogger(__name__)


class FileService:
    """Manage file operations for photogrammetry jobs"""
    
    def __init__(self):
        self.upload_dir = Path(settings.UPLOAD_DIR)
        self.output_dir = Path(settings.OUTPUT_DIR)
        self.temp_dir = Path(settings.TEMP_DIR)
        self.max_file_size = settings.MAX_IMAGE_SIZE_MB * 1024 * 1024
        self.allowed_extensions = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".bmp", ".tiff", ".tif"}
        
        # Ensure directories exist
        for d in [self.upload_dir, self.output_dir, self.temp_dir]:
            d.mkdir(parents=True, exist_ok=True)
    
    async def save_upload(
        self,
        job_id: str,
        files: List[UploadFile],
        validate: bool = True,
    ) -> List[Path]:
        """
        Save uploaded files to job directory
        
        Returns:
            List of saved file paths
        """
        job_upload_dir = self.upload_dir / job_id
        job_upload_dir.mkdir(parents=True, exist_ok=True)
        
        saved_paths = []
        
        for file in files:
            # Validate extension
            ext = Path(file.filename).suffix.lower()
            if validate and ext not in self.allowed_extensions:
                raise ValueError(f"Unsupported file type: {ext}")
            
            # Read content
            content = await file.read()
            
            # Validate size
            if validate and len(content) > self.max_file_size:
                raise ValueError(f"File too large: {file.filename} ({len(content)} bytes)")
            
            # Generate unique filename
            unique_name = f"{uuid.uuid4().hex}{ext}"
            file_path = job_upload_dir / unique_name
            
            # Save file
            with open(file_path, "wb") as f:
                f.write(content)
            
            saved_paths.append(file_path)
            logger.info(f"Saved upload: {file_path}")
        
        return saved_paths
    
    def get_job_upload_dir(self, job_id: str) -> Path:
        """Get job upload directory"""
        return self.upload_dir / job_id
    
    def get_job_output_dir(self, job_id: str) -> Path:
        """Get job output directory"""
        return self.output_dir / job_id
    
    def get_job_temp_dir(self, job_id: str) -> Path:
        """Get job temporary directory"""
        return self.temp_dir / job_id
    
    def list_job_files(self, job_id: str) -> Dict[str, List[Path]]:
        """List all files for a job"""
        return {
            "uploads": list(self.get_job_upload_dir(job_id).glob("*")) if self.get_job_upload_dir(job_id).exists() else [],
            "outputs": list(self.get_job_output_dir(job_id).glob("*")) if self.get_job_output_dir(job_id).exists() else [],
            "temp": list(self.get_job_temp_dir(job_id).glob("*")) if self.get_job_temp_dir(job_id).exists() else [],
        }
    
    def get_result_file(self, job_id: str, format: str) -> Optional[Path]:
        """Get result file path for a specific format"""
        output_dir = self.get_job_output_dir(job_id)
        if not output_dir.exists():
            return None
        
        # Try exact match first
        exact = output_dir / f"model.{format}"
        if exact.exists():
            return exact
        
        # Try case-insensitive
        for f in output_dir.glob(f"model.{format}*"):
            return f
        
        # Try any file with that extension
        for f in output_dir.glob(f"*.{format}"):
            return f
        
        return None
    
    def get_all_results(self, job_id: str) -> Dict[str, Path]:
        """Get all result files for a job"""
        output_dir = self.get_job_output_dir(job_id)
        if not output_dir.exists():
            return {}
        
        results = {}
        for f in output_dir.glob("model.*"):
            ext = f.suffix[1:].lower()  # Remove dot
            results[ext] = f
        
        return results
    
    async def cleanup_job(self, job_id: str, keep_outputs: bool = False) -> Dict[str, int]:
        """
        Clean up job files
        
        Returns:
            Dict with counts of cleaned files
        """
        counts = {"uploads": 0, "outputs": 0, "temp": 0}
        
        # Clean uploads
        upload_dir = self.get_job_upload_dir(job_id)
        if upload_dir.exists():
            counts["uploads"] = len(list(upload_dir.glob("*")))
            shutil.rmtree(upload_dir)
        
        # Clean outputs (optional)
        if not keep_outputs:
            output_dir = self.get_job_output_dir(job_id)
            if output_dir.exists():
                counts["outputs"] = len(list(output_dir.glob("*")))
                shutil.rmtree(output_dir)
        
        # Clean temp
        temp_dir = self.get_job_temp_dir(job_id)
        if temp_dir.exists():
            counts["temp"] = len(list(temp_dir.glob("*")))
            shutil.rmtree(temp_dir)
        
        logger.info(f"Cleaned job {job_id}: {counts}")
        return counts
    
    async def cleanup_old_jobs(self, max_age_hours: int = 24, dry_run: bool = False) -> Dict[str, Any]:
        """
        Clean up old job directories
        
        Args:
            max_age_hours: Maximum age of job directories to keep
            dry_run: If True, only report what would be deleted
            
        Returns:
            Cleanup report
        """
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        cleaned = {"uploads": 0, "outputs": 0, "temp": 0, "errors": []}
        
        for base_dir, key in [
            (self.upload_dir, "uploads"),
            (self.output_dir, "outputs"),
            (self.temp_dir, "temp"),
        ]:
            if not base_dir.exists():
                continue
            
            for job_dir in base_dir.iterdir():
                if not job_dir.is_dir():
                    continue
                
                # Check directory age
                try:
                    mtime = datetime.fromtimestamp(job_dir.stat().st_mtime)
                    if mtime < cutoff:
                        if not dry_run:
                            try:
                                shutil.rmtree(job_dir)
                                cleaned[key] += 1
                            except Exception as e:
                                cleaned["errors"].append(f"Failed to delete {job_dir}: {e}")
                        else:
                            cleaned[key] += 1
                except Exception as e:
                    cleaned["errors"].append(f"Error checking {job_dir}: {e}")
        
        logger.info(f"Cleanup old jobs: {cleaned}")
        return cleaned
    
    def get_disk_usage(self) -> Dict[str, Any]:
        """Get disk usage statistics"""
        import shutil as sh
        
        usage = {}
        for name, path in [
            ("uploads", self.upload_dir),
            ("outputs", self.output_dir),
            ("temp", self.temp_dir),
        ]:
            if path.exists():
                total, used, free = sh.disk_usage(path)
                usage[name] = {
                    "total_gb": round(total / (1024**3), 2),
                    "used_gb": round(used / (1024**3), 2),
                    "free_gb": round(free / (1024**3), 2),
                    "path": str(path),
                }
            else:
                usage[name] = {"error": "Directory does not exist"}
        
        return usage
    
    async def create_job_package(self, job_id: str, format: str = "zip") -> Optional[Path]:
        """
        Create a downloadable package of all job results
        
        Args:
            job_id: Job ID
            format: Archive format (zip, tar.gz)
            
        Returns:
            Path to created package
        """
        output_dir = self.get_job_output_dir(job_id)
        if not output_dir.exists():
            return None
        
        package_path = self.output_dir / f"{job_id}_results.{format}"
        
        if format == "zip":
            import zipfile
            with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in output_dir.rglob("*"):
                    if f.is_file():
                        zf.write(f, f.relative_to(output_dir))
        elif format == "tar.gz":
            import tarfile
            with tarfile.open(package_path, "w:gz") as tf:
                tf.add(output_dir, arcname=job_id)
        else:
            raise ValueError(f"Unsupported format: {format}")
        
        return package_path


# Global file service instance
file_service = FileService()


async def get_file_service() -> FileService:
    """Dependency to get file service"""
    return file_service