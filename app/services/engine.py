"""
PolyFree C++ Core Engine Integration Service
Integrates the native C++ photogrammetry engine (libpolyfree_core.a) with FastAPI
"""
import asyncio
import json
import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class PolyFreeEngineService:
    """Service for integrating with PolyFree C++ core engine"""
    
    def __init__(self):
        self.engine_path = os.environ.get(
            "POLYFREE_ENGINE_PATH",
            "/opt/polyfree/bin/polyfree_pipeline"  # Default Docker path
        )
        self.library_path = os.environ.get(
            "POLYFREE_LIB_PATH",
            "/opt/polyfree/lib/libpolyfree_core.a"
        )
        self.available = self._check_availability()
    
    def _check_availability(self) -> bool:
        """Check if PolyFree engine is available"""
        # Check for shared library or executable
        paths_to_check = [
            self.engine_path,
            self.library_path,
            "/usr/local/lib/libpolyfree_core.so",
            "/usr/local/lib/libpolyfree_core.dylib",
            "build25/lib/libpolyfree_core.a",  # Local build
        ]
        
        for path in paths_to_check:
            if os.path.exists(path):
                logger.info(f"PolyFree engine found at: {path}")
                return True
        
        logger.warning("PolyFree engine not found - will use COLMAP fallback")
        return False
    
    async def run_pipeline(
        self,
        job_id: str,
        image_paths: List[str],
        quality: str = "high",
        reconstruction_type: str = "mesh",
        output_formats: List[str] = None,
        texture: bool = True,
        max_faces: Optional[int] = None,
        scale: Optional[float] = None,
        progress_callback=None,
    ) -> Dict[str, str]:
        """
        Run the complete photogrammetry pipeline using PolyFree core engine
        
        Returns:
            Dict mapping format -> output file path
        """
        if output_formats is None:
            output_formats = ["stl", "obj", "gltf", "ply"]
        
        work_dir = Path(f"/tmp/photogrammetry/{job_id}")
        images_dir = work_dir / "images"
        output_dir = Path(f"/data/outputs/{job_id}")
        
        images_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        def update_progress(progress: float, step: str, message: str = ""):
            if progress_callback:
                progress_callback(progress, step, message)
            logger.info(f"Job {job_id}: {step} - {progress:.1%} - {message}")
        
        try:
            if self.available:
                return await self._run_polyfree_core(
                    job_id, image_paths, quality, reconstruction_type,
                    output_formats, texture, max_faces, scale,
                    work_dir, images_dir, output_dir, update_progress
                )
            else:
                # Fallback to COLMAP pipeline
                logger.info("Using COLMAP fallback pipeline")
                return await self._run_colmap_fallback(
                    job_id, image_paths, quality, reconstruction_type,
                    output_formats, texture, max_faces, scale,
                    work_dir, images_dir, output_dir, update_progress
                )
                
        except Exception as e:
            logger.error(f"Pipeline failed for job {job_id}: {e}", exc_info=True)
            raise
    
    async def _run_polyfree_core(
        self,
        job_id: str,
        image_paths: List[str],
        quality: str,
        reconstruction_type: str,
        output_formats: List[str],
        texture: bool,
        max_faces: Optional[int],
        scale: Optional[float],
        work_dir: Path,
        images_dir: Path,
        output_dir: Path,
        progress_callback,
    ) -> Dict[str, str]:
        """Run pipeline using native PolyFree C++ core"""
        
        progress_callback(0.05, "preparing", "Preparing images for PolyFree engine...")
        
        # Copy images to work directory
        for i, src in enumerate(image_paths):
            dst = images_dir / f"{i:04d}.jpg"
            shutil.copy2(src, dst)
        
        # Create config for PolyFree engine
        config = {
            "job_id": job_id,
            "images_dir": str(images_dir),
            "output_dir": str(output_dir),
            "quality": quality,
            "reconstruction_type": reconstruction_type,
            "output_formats": output_formats,
            "texture": texture,
            "max_faces": max_faces or 500000,
            "scale": scale,
        }
        
        config_path = work_dir / "config.json"
        with open(config_path, "w") as f:
            json.dump(config, f)
        
        progress_callback(0.15, "sfm", "Running Structure from Motion...")
        
        # Run PolyFree engine via subprocess
        # This assumes we have a polyfree_pipeline executable
        if os.path.exists(self.engine_path):
            result = await self._run_polyfree_executable(config_path, progress_callback)
        else:
            # Try using Python bindings if available
            result = await self._run_polyfree_python_bindings(config, progress_callback)
        
        # Collect result files
        result_files = {}
        for fmt in output_formats:
            output_path = output_dir / f"model.{fmt}"
            if output_path.exists():
                result_files[fmt] = str(output_path)
        
        return result_files
    
    async def _run_polyfree_executable(self, config_path: Path, progress_callback) -> Dict[str, Any]:
        """Run PolyFree engine executable"""
        cmd = [self.engine_path, "--config", str(config_path)]
        
        progress_callback(0.2, "processing", "Starting PolyFree engine...")
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        # Monitor progress from stdout
        async for line in process.stdout:
            line = line.decode().strip()
            if line.startswith("PROGRESS:"):
                # Expected format: PROGRESS:0.5:sfm:Running SfM...
                parts = line.split(":", 3)
                if len(parts) >= 4:
                    progress = float(parts[1])
                    step = parts[2]
                    message = parts[3]
                    progress_callback(progress, step, message)
        
        await process.wait()
        
        if process.returncode != 0:
            stderr = await process.stderr.read()
            raise RuntimeError(f"PolyFree engine failed: {stderr.decode()}")
        
        return {"success": True}
    
    async def _run_polyfree_python_bindings(self, config: Dict, progress_callback) -> Dict[str, Any]:
        """Run PolyFree engine via Python bindings"""
        try:
            import polyfree
            
            progress_callback(0.2, "initializing", "Initializing PolyFree Python bindings...")
            
            # Create pipeline
            pipeline = polyfree.PhotogrammetryPipeline()
            
            def native_callback(progress, step, message):
                progress_callback(progress, step, message)
            
            # Set up pipeline with config
            results = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: pipeline.run(
                    images_dir=config["images_dir"],
                    output_dir=config["output_dir"],
                    quality=config["quality"],
                    reconstruction_type=config["reconstruction_type"],
                    output_formats=config["output_formats"],
                    texture=config["texture"],
                    max_faces=config["max_faces"],
                    scale=config["scale"],
                    progress_callback=native_callback,
                )
            )
            
            return results
            
        except ImportError:
            logger.warning("PolyFree Python bindings not available")
            raise RuntimeError("PolyFree Python bindings not installed")
    
    async def _run_colmap_fallback(
        self,
        job_id: str,
        image_paths: List[str],
        quality: str,
        reconstruction_type: str,
        output_formats: List[str],
        texture: bool,
        max_faces: Optional[int],
        scale: Optional[float],
        work_dir: Path,
        images_dir: Path,
        output_dir: Path,
        progress_callback,
    ) -> Dict[str, str]:
        """Fallback to COLMAP + Open3D pipeline"""
        # Import the existing pipeline
        from app.services.pipeline import PhotogrammetryPipeline as ColmapPipeline
        from app.core.config import QUALITY_PRESETS
        from app.models.schemas import ReconstructionQuality
        
        quality_enum = ReconstructionQuality(quality)
        
        pipeline = ColmapPipeline(job_id, quality_enum)
        
        def status_callback(progress, step, message):
            progress_callback(progress, step, message)
        
        pipeline.set_status_callback(status_callback)
        
        # Convert image paths
        path_objects = [Path(p) for p in image_paths]
        
        result_files = await pipeline.run_pipeline(
            image_paths=path_objects,
            reconstruction_type=reconstruction_type,
            output_formats=output_formats,
            texture=texture,
            max_faces=max_faces,
            scale=scale,
        )
        
        # Convert to string paths
        return {k: str(v) for k, v in result_files.items()}


# Global engine service instance
engine_service = PolyFreeEngineService()


async def get_engine_service() -> PolyFreeEngineService:
    """Dependency to get engine service"""
    return engine_service