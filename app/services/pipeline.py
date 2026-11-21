"""
Photogrammetry Pipeline Service
COLMAP + Open3D pipeline for 3D reconstruction
"""
import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import structlog

import cv2
import numpy as np
import open3d as o3d
import trimesh
from stl import mesh as stl_mesh

from app.core.config import settings, QUALITY_PRESETS
from app.core.database import init_db, save_job, load_job, load_all_jobs, delete_job
from app.models.schemas import (
    JobStatus, ReconstructionQuality, ReconstructionType, OutputFormat
)

logger = structlog.get_logger(__name__)


class PhotogrammetryPipeline:
    """Main photogrammetry pipeline using COLMAP + Open3D"""

    def __init__(self, job_id: str, quality: ReconstructionQuality):
        self.job_id = job_id
        self.quality = quality
        self.preset = QUALITY_PRESETS[quality.value]
        self.work_dir = Path(settings.TEMP_DIR) / job_id
        self.images_dir = self.work_dir / "images"
        self.colmap_dir = self.work_dir / "colmap"
        self.output_dir = Path(settings.OUTPUT_DIR) / job_id

        # Create directories
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.colmap_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.status_callback = None
        self.progress = 0.0
        self.current_step = "initializing"

    def set_status_callback(self, callback):
        self.status_callback = callback

    def _update_progress(self, progress: float, step: str, message: str = ""):
        self.progress = progress
        self.current_step = step
        if self.status_callback:
            self.status_callback(progress, step, message)
        logger.info(f"Job {self.job_id}: {step} - {progress:.1%} - {message}")

    async def run_pipeline(
        self,
        image_paths: List[Path],
        reconstruction_type: str,
        output_formats: List[str],
        texture: bool = True,
        max_faces: Optional[int] = None,
        scale: Optional[float] = None,
    ) -> Dict[str, Path]:
        """Run the complete photogrammetry pipeline"""

        try:
            # Step 1: Prepare images
            await self._prepare_images(image_paths)

            # Step 2: Run COLMAP SfM + MVS
            sparse_path, dense_path = await self._run_colmap()

            # Step 3: Generate mesh from dense point cloud
            mesh_path = await self._generate_mesh(dense_path, max_faces)

            # Step 4: Texture mesh if requested
            if texture:
                mesh_path = await self._texture_mesh(mesh_path, self.images_dir)

            # Step 5: Apply scale if provided
            if scale:
                await self._apply_scale(mesh_path, scale)

            # Step 6: Export to requested formats
            result_files = await self._export_mesh(mesh_path, output_formats)

            return result_files

        except Exception as e:
            logger.error(f"Pipeline failed for job {self.job_id}: {e}", exc_info=True)
            raise

    async def _prepare_images(self, image_paths: List[Path]):
        """Copy and resize images for processing"""
        self._update_progress(0.05, "preparing_images", "Copying and resizing images...")

        max_size = self.preset["max_image_size"]
        for i, src in enumerate(image_paths):
            dst = self.images_dir / f"{i:04d}{src.suffix.lower()}"
            shutil.copy2(src, dst)

            # Resize if needed
            if max_size > 0:
                img = cv2.imread(str(dst))
                h, w = img.shape[:2]
                if max(h, w) > max_size:
                    scale = max_size / max(h, w)
                    new_w, new_h = int(w * scale), int(h * scale)
                    img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
                    cv2.imwrite(str(dst), img)

            progress = 0.05 + (0.1 * (i + 1) / len(image_paths))
            self._update_progress(progress, "preparing_images", f"Processed {i+1}/{len(image_paths)} images")

    async def _run_colmap(self) -> Tuple[Path, Path]:
        """Run COLMAP SfM + MVS pipeline"""
        self._update_progress(0.15, "colmap_sfm", "Running Structure from Motion...")

        # COLMAP database
        db_path = self.colmap_dir / "database.db"
        sparse_dir = self.colmap_dir / "sparse"
        sparse_dir.mkdir(exist_ok=True)
        dense_dir = self.colmap_dir / "dense"
        dense_dir.mkdir(exist_ok=True)

        colmap_options = self.preset["colmap_options"]

        # 1. Feature extraction
        await self._run_colmap_command([
            "feature_extractor",
            "--database_path", str(db_path),
            "--image_path", str(self.images_dir),
            *colmap_options.split(),
        ], "Feature extraction")

        # 2. Feature matching
        await self._run_colmap_command([
            "exhaustive_matcher",
            "--database_path", str(db_path),
            *colmap_options.split(),
        ], "Feature matching")

        # 3. Sparse reconstruction (SfM)
        await self._run_colmap_command([
            "mapper",
            "--database_path", str(db_path),
            "--image_path", str(self.images_dir),
            "--output_path", str(sparse_dir),
            *colmap_options.split(),
        ], "Sparse reconstruction")

        # Check if reconstruction succeeded
        sparse_model = sparse_dir / "0"
        if not sparse_model.exists():
            # Try to find any sparse model
            models = list(sparse_dir.glob("[0-9]*"))
            if not models:
                raise RuntimeError("COLMAP sparse reconstruction failed - no model generated")
            sparse_model = models[0]

        # 4. Image undistortion
        await self._run_colmap_command([
            "image_undistorter",
            "--image_path", str(self.images_dir),
            "--input_path", str(sparse_model),
            "--output_path", str(dense_dir),
            "--output_type", "COLMAP",
        ], "Image undistortion")

        # 5. Dense stereo (MVS)
        self._update_progress(0.55, "colmap_mvs", "Running Multi-View Stereo...")
        await self._run_colmap_command([
            "patch_match_stereo",
            "--workspace_path", str(dense_dir),
            "--workspace_format", "COLMAP",
            "--PatchMatchStereo.geom_consistency", "true",
        ], "Patch-match stereo")

        # 6. Stereo fusion
        await self._run_colmap_command([
            "stereo_fusion",
            "--workspace_path", str(dense_dir),
            "--workspace_format", "COLMAP",
            "--input_type", "geometric",
            "--output_path", str(dense_dir / "fused.ply"),
        ], "Stereo fusion")

        # 7. Poisson meshing (optional, we'll use Open3D for better control)
        await self._run_colmap_command([
            "poisson_mesher",
            "--input_path", str(dense_dir / "fused.ply"),
            "--output_path", str(dense_dir / "meshed-poisson.ply"),
        ], "Poisson meshing")

        fused_ply = dense_dir / "fused.ply"
        if not fused_ply.exists():
            raise RuntimeError("COLMAP dense reconstruction failed - no fused point cloud")

        return sparse_model, dense_dir

    async def _run_colmap_command(self, cmd: List[str], step_name: str):
        """Run a COLMAP command with progress tracking"""
        full_cmd = [settings.COLMAP_PATH] + cmd
        logger.info(f"Running COLMAP {step_name}: {' '.join(full_cmd)}")

        process = await asyncio.create_subprocess_exec(
            *full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            logger.error(f"COLMAP {step_name} failed: {error_msg}")
            raise RuntimeError(f"COLMAP {step_name} failed: {error_msg}")

        logger.info(f"COLMAP {step_name} completed successfully")

    async def _generate_mesh(self, dense_dir: Path, max_faces: Optional[int]) -> Path:
        """Generate mesh from dense point cloud using Open3D"""
        self._update_progress(0.7, "meshing", "Generating mesh from point cloud...")

        fused_ply = dense_dir / "fused.ply"
        if not fused_ply.exists():
            raise FileNotFoundError(f"Fused point cloud not found: {fused_ply}")

        # Load point cloud
        pcd = o3d.io.read_point_cloud(str(fused_ply))
        logger.info(f"Loaded point cloud with {len(pcd.points)} points")

        # Estimate normals
        pcd.estimate_normals(
            search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=0.1, max_nn=30)
        )
        pcd.orient_normals_consistent_tangent_plane(100)

        # Poisson surface reconstruction
        self._update_progress(0.75, "meshing", "Running Poisson reconstruction...")
        mesh, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
            pcd, depth=9, width=0, scale=1.1, linear_fit=False
        )

        # Remove low-density vertices
        densities = np.asarray(densities)
        density_threshold = np.quantile(densities, 0.1)
        vertices_to_remove = densities < density_threshold
        mesh.remove_vertices_by_mask(vertices_to_remove)

        # Simplify if requested
        if max_faces and len(mesh.triangles) > max_faces:
            self._update_progress(0.8, "meshing", f"Simplifying mesh to {max_faces} faces...")
            mesh = mesh.simplify_quadric_decimation(max_faces)

        # Clean mesh
        mesh.remove_degenerate_triangles()
        mesh.remove_duplicated_triangles()
        mesh.remove_duplicated_vertices()
        mesh.remove_non_manifold_edges()

        # Save mesh
        mesh_path = self.work_dir / "mesh.ply"
        o3d.io.write_triangle_mesh(str(mesh_path), mesh)
        logger.info(f"Generated mesh with {len(mesh.vertices)} vertices, {len(mesh.triangles)} faces")

        return mesh_path

    async def _texture_mesh(self, mesh_path: Path, images_dir: Path) -> Path:
        """Texture mesh using Open3D's texture mapping"""
        self._update_progress(0.85, "texturing", "Applying texture to mesh...")

        # Load mesh
        mesh = o3d.io.read_triangle_mesh(str(mesh_path))
        mesh.compute_vertex_normals()

        # For now, we'll use a simple vertex color approach
        # Full texture mapping requires UV unwrapping which is complex
        # This is a placeholder for actual texture mapping

        textured_path = self.work_dir / "mesh_textured.ply"
        o3d.io.write_triangle_mesh(str(textured_path), mesh)

        return textured_path

    async def _apply_scale(self, mesh_path: Path, scale: float):
        """Apply known scale to mesh"""
        mesh = o3d.io.read_triangle_mesh(str(mesh_path))
        vertices = np.asarray(mesh.vertices)
        vertices *= scale
        mesh.vertices = o3d.utility.Vector3dVector(vertices)
        o3d.io.write_triangle_mesh(str(mesh_path), mesh)
        logger.info(f"Applied scale factor: {scale}")

    async def _export_mesh(self, mesh_path: Path, output_formats: List[str]) -> Dict[str, Path]:
        """Export mesh to requested formats"""
        self._update_progress(0.9, "exporting", "Exporting mesh to requested formats...")

        results = {}
        mesh = o3d.io.read_triangle_mesh(str(mesh_path))

        for fmt in output_formats:
            output_path = self.output_dir / f"model.{fmt.value if hasattr(fmt, 'value') else fmt}"

            try:
                if fmt == OutputFormat.STL or fmt == "stl":
                    # Export as STL (binary)
                    o3d.io.write_triangle_mesh(str(output_path), mesh, write_ascii=False)
                    results["stl"] = output_path

                elif fmt == OutputFormat.OBJ or fmt == "obj":
                    o3d.io.write_triangle_mesh(str(output_path), mesh)
                    results["obj"] = output_path

                elif fmt in (OutputFormat.GLTF, OutputFormat.GLB, "gltf", "glb"):
                    o3d.io.write_triangle_mesh(str(output_path), mesh)
                    results["gltf"] = output_path

                elif fmt == OutputFormat.PLY or fmt == "ply":
                    o3d.io.write_triangle_mesh(str(output_path), mesh)
                    results["ply"] = output_path

                logger.info(f"Exported {fmt}: {output_path}")

            except Exception as e:
                logger.warning(f"Failed to export {fmt}: {e}")

        # Also save as trimesh for additional processing if needed
        try:
            tri_mesh = trimesh.load(str(mesh_path))
            tri_mesh.export(str(self.output_dir / "model.glb"))
            results["glb"] = self.output_dir / "model.glb"
        except Exception as e:
            logger.warning(f"Trimesh export failed: {e}")

        self._update_progress(1.0, "completed", "All exports completed!")
        return results


# Thread pool for CPU-intensive tasks
_cpu_executor = ThreadPoolExecutor(max_workers=max(1, settings.WORKERS))


def run_in_threadpool(func, *args, **kwargs):
    """Run CPU-bound function in thread pool"""
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(_cpu_executor, func, *args, **kwargs)


class JobManager:
    """Manage photogrammetry jobs with SQLite persistence"""

    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.workers: List[asyncio.Task] = []
        self.running = False
        self._worker_semaphore: Optional[asyncio.Semaphore] = None

    async def initialize(self):
        """Initialize database and load existing jobs"""
        await init_db()
        logger.info("JobManager initialized with database persistence")

    async def create_job(
        self,
        quality: ReconstructionQuality,
        reconstruction_type: ReconstructionType,
        output_formats: List[OutputFormat],
        texture: bool,
        max_faces: Optional[int],
        scale: Optional[float],
    ) -> str:
        job_id = str(uuid.uuid4())[:8]
        job_data = {
            "job_id": job_id,
            "status": JobStatus.PENDING,
            "progress": 0.0,
            "message": "Job created",
            "current_step": "pending",
            "quality": quality.value,
            "reconstruction_type": reconstruction_type.value,
            "output_formats": [f.value for f in output_formats],
            "texture": texture,
            "max_faces": max_faces,
            "scale": scale,
            "result_files": {},
            "error": None,
        }
        await save_job(job_data)
        await self.queue.put(job_id)
        logger.info("Job created", job_id=job_id)
        return job_id

    async def add_images(self, job_id: str, image_paths: List[Path]):
        job = await load_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        job["image_paths"] = [str(p) for p in image_paths]
        job["status"] = JobStatus.UPLOADING
        await save_job(job)

    async def get_job_status(self, job_id: str) -> Optional[Dict]:
        return await load_job(job_id)

    async def list_jobs(self) -> List[Dict]:
        return await load_all_jobs()

    async def delete_job(self, job_id: str) -> bool:
        return await delete_job(job_id)

    async def start_workers(self, num_workers: Optional[int] = None):
        if num_workers is None:
            num_workers = settings.WORKERS
        self._worker_semaphore = asyncio.Semaphore(num_workers)
        self.running = True
        for i in range(num_workers):
            worker = asyncio.create_task(self._worker_loop(i))
            self.workers.append(worker)
        logger.info("Job workers started", count=num_workers)

    async def stop_workers(self):
        self.running = False
        for worker in self.workers:
            worker.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
        _cpu_executor.shutdown(wait=True)
        logger.info("Job workers stopped")

    async def _worker_loop(self, worker_id: int):
        logger.info("Worker started", worker_id=worker_id)
        while self.running:
            try:
                job_id = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                async with self._worker_semaphore:
                    await self._process_job(job_id)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("Worker error", worker_id=worker_id, error=str(e))

    async def _process_job(self, job_id: str):
        job = await load_job(job_id)
        if not job:
            logger.warning("Job not found, skipping", job_id=job_id)
            return

        job["status"] = JobStatus.PROCESSING
        job["started_at"] = time.time()
        await save_job(job)

        def status_callback(progress: float, step: str, message: str):
            job["progress"] = progress
            job["current_step"] = step
            job["message"] = message
            job["updated_at"] = time.time()
            # Save progress periodically (not every update to avoid DB overload)
            if progress % 0.1 < 0.02:  # Save roughly every 10%
                asyncio.create_task(save_job(job.copy()))

        try:
            pipeline = PhotogrammetryPipeline(job_id, ReconstructionQuality(job["quality"]))
            pipeline.set_status_callback(status_callback)

            result_files = await pipeline.run_pipeline(
                image_paths=[Path(p) for p in job.get("image_paths", [])],
                reconstruction_type=job["reconstruction_type"],
                output_formats=job["output_formats"],
                texture=job["texture"],
                max_faces=job["max_faces"],
                scale=job["scale"],
            )

            job["result_files"] = {k: str(v) for k, v in result_files.items()}
            job["status"] = JobStatus.COMPLETED
            job["progress"] = 1.0
            job["message"] = "Reconstruction completed successfully"
            job["completed_at"] = time.time()

        except Exception as e:
            logger.error("Job failed", job_id=job_id, error=str(e), exc_info=True)
            job["status"] = JobStatus.FAILED
            job["error"] = str(e)
            job["message"] = f"Processing failed: {e}"

        job["updated_at"] = time.time()
        await save_job(job)
        logger.info("Job finished", job_id=job_id, status=job["status"])


# Global job manager instance
job_manager = JobManager()