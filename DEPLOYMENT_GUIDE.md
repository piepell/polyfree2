# PolyFree Photogrammetry System - Deployment Guide

## System Overview

PolyFree is a complete photogrammetry pipeline that converts photos into 3D models (STL, OBJ, GLTF, PLY, etc.). The system consists of:

1. **C++ Core Engine** (`build25/lib/libpolyfree_core.a`) - High-performance SfM/MVS pipeline
2. **FastAPI Backend** - REST API for job management and processing
3. **Android Clients** - PhotoSphereGuide (capture) and PhotoSphereClient (processing)
4. **Docker Deployment** - Containerized deployment with GPU support

---

## Quick Start

### Prerequisites

- **Windows 10/11** or **Linux** (Ubuntu 22.04+)
- **Python 3.10+** (tested with 3.14)
- **C++17 Compiler** (MSVC on Windows, GCC/Clang on Linux)
- **NVIDIA GPU** (optional, for CUDA acceleration)
- **Docker** (optional, for containerized deployment)

### 1. C++ Core Engine

```bash
# Build the core library
cd /path/to/polyfree
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
ninja

# Result: build/lib/libpolyfree_core.a (176 KB)
# Headers: ../include/
```

### 2. FastAPI Backend

```bash
# Install dependencies
cd PhotogrammetryBackend
pip install -r requirements.txt

# Run development server
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Or use Docker
docker build --target cpu -t photogrammetry-backend .
docker run -p 8000:8000 -v ./data:/data photogrammetry-backend

# GPU version (requires NVIDIA Docker)
docker build --target gpu -t photogrammetry-backend-gpu .
docker run --gpus all -p 8000:8000 -v ./data:/data photogrammetry-backend-gpu
```

### 3. Access API Documentation

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/api/health

---

## API Endpoints

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/token` | Get JWT access token |
| POST | `/api/auth/api-keys` | Create API key (auth required) |
| GET | `/api/auth/api-keys` | List API keys (auth required) |
| DELETE | `/api/auth/api-keys/{prefix}` | Revoke API key (auth required) |

### Job Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/jobs` | Create new photogrammetry job |
| POST | `/api/jobs/{id}/upload` | Upload images for job |
| POST | `/api/jobs/{id}/start` | Start processing job |
| GET | `/api/jobs/{id}/status` | Get job status & progress |
| GET | `/api/jobs/{id}/download/{format}` | Download result file |
| GET | `/api/jobs/{id}/package` | Download all results as ZIP/TAR.GZ |
| DELETE | `/api/jobs/{id}` | Delete job and files |
| GET | `/api/jobs` | List all jobs (with filters) |

### Engine Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/engine/status` | Get engine availability & capabilities |
| POST | `/api/engine/configure` | Configure engine paths (admin) |

### System Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/system/disk` | Disk usage statistics (auth required) |
| POST | `/api/system/cleanup` | Clean old job files (auth required) |
| GET | `/api/system/info` | System information |

---

## Job Processing Flow

```
1. POST /api/jobs          → Create job (returns job_id)
2. POST /api/jobs/{id}/upload  → Upload 20-200 images
3. POST /api/jobs/{id}/start   → Queue job for processing
4. GET  /api/jobs/{id}/status  → Monitor progress (0-100%)
5. GET  /api/jobs/{id}/download/{format}  → Download results
```

### Job Parameters

```json
{
  "quality": "high",           // "low", "medium", "high"
  "reconstruction_type": "mesh",  // "mesh", "3dgs", "nerf"
  "output_formats": ["stl", "obj", "gltf"],
  "texture": true,
  "max_faces": 500000,
  "scale": null
}
```

### Quality Presets

| Quality | Max Images | Max Image Size | COLMAP Features |
|---------|------------|----------------|-----------------|
| Low | 50 | 1024px | 8192 |
| Medium | 100 | 2048px | 16384 |
| High | 200 | 4096px | 32768 |

---

## Docker Deployment

### CPU-Only (Recommended for Testing)

```dockerfile
# Use the CPU stage
FROM photogrammetry-backend:cpu

# Run
docker run -d \
  --name photogrammetry \
  -p 8000:8000 \
  -v $(pwd)/data:/data \
  -v $(pwd)/outputs:/data/outputs \
  photogrammetry-backend:cpu
```

### GPU-Accelerated (Production)

```dockerfile
# Use the GPU stage
FROM photogrammetry-backend:gpu

# Run with NVIDIA Docker
docker run -d \
  --name photogrammetry-gpu \
  --gpus all \
  -p 8000:8000 \
  -v $(pwd)/data:/data \
  -v $(pwd)/outputs:/data/outputs \
  photogrammetry-backend:gpu
```

### Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  photogrammetry:
    build:
      context: ./PhotogrammetryBackend
      target: cpu
    ports:
      - "8000:8000"
    volumes:
      - ./data:/data
      - ./outputs:/data/outputs
    environment:
      - USE_GPU=false
    restart: unless-stopped

  photogrammetry-gpu:
    build:
      context: ./PhotogrammetryBackend
      target: gpu
    ports:
      - "8001:8000"
    volumes:
      - ./data:/data
      - ./outputs:/data/outputs
    environment:
      - USE_GPU=true
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    restart: unless-stopped
```

---

## Android Client Integration

### PhotoSphereGuide (Capture App)

The capture app guides users through 20-position spherical capture for optimal photogrammetry.

**API Integration:**
```kotlin
// Create job
val job = api.createJob(
    quality = "high",
    reconstructionType = "mesh",
    outputFormats = listOf("stl", "obj", "gltf")
)

// Upload images
api.uploadImages(job.jobId, imageFiles)

// Start processing
api.startJob(job.jobId)

// Poll status
while (true) {
    val status = api.getJobStatus(job.jobId)
    if (status.status == "completed") break
    if (status.status == "failed") throw Exception(status.error)
    delay(5000)
}

// Download results
val stlFile = api.downloadResult(job.jobId, "stl")
val objFile = api.downloadResult(job.jobId, "obj")
```

### PhotoSphereClient (Processing App)

Standalone client for managing photogrammetry jobs on-device or via cloud.

---

## C++ Core Engine Integration

### Using the Static Library

```cpp
// Link against: build/lib/libpolyfree_core.a
// Include: include/
// Dependencies: Eigen3, OpenCV, nlohmann_json

#include "polyfree/sfm_engine.hpp"
#include "polyfree/pipeline.hpp"

int main() {
    polyfree::SfMEngine engine;
    polyfree::PhotogrammetryPipeline pipeline;
    
    // Add images
    for (const auto& image : images) {
        engine.addFrame(image, intrinsics);
    }
    
    // Run SfM
    auto sfm_result = engine.getResult();
    
    // Export
    sfm_result.exportPLY("output.ply");
    sfm_result.exportSTL("output.stl");
    sfm_result.exportGLTF("output.gltf");
}
```

### Engine Capabilities

| Feature | Status | Notes |
|---------|--------|-------|
| SfM (Structure from Motion) | ✅ Complete | Feature extraction, matching, pose estimation, triangulation |
| MVS (Multi-View Stereo) | ✅ Complete | Depth maps, point cloud fusion |
| Mesh Generation | ✅ Complete | Poisson reconstruction, simplification |
| Texturing | ✅ Complete | UV unwrapping, texture baking |
| Export Formats | ✅ Complete | STL, OBJ, GLTF, PLY, XYZ, PTS |

---

## Configuration

### Environment Variables

```bash
# Backend
export HOST=0.0.0.0
export PORT=8000
export WORKERS=1
export SECRET_KEY=your-secret-key
export UPLOAD_DIR=/data/uploads
export OUTPUT_DIR=/data/outputs
export TEMP_DIR=/tmp/photogrammetry

# Engine
export POLYFREE_ENGINE_PATH=/opt/polyfree/bin/polyfree_pipeline
export POLYFREE_LIB_PATH=/opt/polyfree/lib/libpolyfree_core.so

# COLMAP (fallback)
export COLMAP_PATH=colmap

# GPU
export USE_GPU=true
export GPU_DEVICE=0
```

### .env File

```env
# PhotogrammetryBackend/.env
HOST=0.0.0.0
PORT=8000
WORKERS=1
SECRET_KEY=dev-secret-change-in-production
ACCESS_TOKEN_EXPIRE_MINUTES=1440
MAX_IMAGES=200
MAX_IMAGE_SIZE_MB=50
COLMAP_QUALITY=high
USE_GPU=true
GPU_DEVICE=0
UPLOAD_DIR=/data/uploads
OUTPUT_DIR=/data/outputs
TEMP_DIR=/tmp/photogrammetry
COLMAP_PATH=colmap
```

---

## Monitoring & Maintenance

### Health Checks

```bash
# API health
curl http://localhost:8000/api/health

# System info
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/system/info

# Disk usage
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/system/disk
```

### Cleanup Old Jobs

```bash
# Auto-cleanup jobs older than 24 hours
curl -X POST -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/system/cleanup?max_age_hours=24"

# Dry run
curl -X POST -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/system/cleanup?max_age_hours=24&dry_run=true"
```

### Logs

```bash
# Docker logs
docker logs photogrammetry -f

# Uvicorn logs (development)
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level debug
```

---

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError: fastapi` | Run `pip install -r requirements.txt` |
| `COLMAP not found` | Install COLMAP or use Docker GPU image |
| `CUDA out of memory` | Reduce `MAX_IMAGES` or use `quality: "low"` |
| `Permission denied /data` | Run `chmod 777 /data` or fix Docker volumes |
| `Job fails immediately` | Check image format (JPG/PNG), size (<50MB), count (≤200) |

### Performance Tuning

| Setting | Low | Medium | High |
|---------|-----|--------|------|
| Max Images | 50 | 100 | 200 |
| Image Size | 1024px | 2048px | 4096px |
| Features | 8192 | 16384 | 32768 |
| Processing Time | ~5 min | ~15 min | ~45 min |

---

## Security

### Production Checklist

- [ ] Change `SECRET_KEY` to strong random value
- [ ] Use HTTPS (reverse proxy with nginx/Traefik)
- [ ] Restrict CORS origins in `app/main.py`
- [ ] Enable API key authentication for all endpoints
- [ ] Set up rate limiting
- [ ] Configure firewall rules
- [ ] Regular security updates

### Authentication

```bash
# Get token
curl -X POST http://localhost:8000/api/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"your-password"}'

# Use token
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/jobs

# Or use API key
curl -H "Authorization: Bearer pf_xxxxxxxx" http://localhost:8000/api/jobs
```

---

## Support

- **Documentation**: `/docs` endpoint when server running
- **Issues**: Check logs with `docker logs photogrammetry`
- **Performance**: Monitor `/api/system/info` and `/api/system/disk`

---

**PolyFree Photogrammetry System v1.0.0**  
Built with C++, Python, FastAPI, COLMAP, Open3D, and ❤️