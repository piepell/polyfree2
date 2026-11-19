# Photogrammetry Backend

Cloud photogrammetry API: **Upload photos → Get 3D models (STL, OBJ, GLTF, PLY)**

## Features

- **COLMAP + Open3D Pipeline**: Industry-standard SfM + MVS + Poisson reconstruction
- **GPU Acceleration**: CUDA support for feature extraction, matching, and dense reconstruction
- **Multiple Quality Presets**: Low / Medium / High
- **Multiple Output Formats**: STL, OBJ, GLTF/GLB, PLY
- **Async Job Processing**: Upload → Queue → Process → Download
- **REST API**: Easy integration with Android/iOS/Web clients
- **Docker Support**: CPU and GPU variants

## Quick Start

### Option 1: Docker (Recommended)

```bash
# GPU version (requires NVIDIA GPU + nvidia-container-toolkit)
docker-compose up photogrammetry-gpu

# CPU version
docker-compose up photogrammetry-cpu
```

### Option 2: Local Development

```bash
# Install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Install COLMAP
# Ubuntu: sudo apt install colmap
# macOS: brew install colmap
# Windows: Download from https://colmap.github.io/

# Run
python -m app.main
```

## API Usage

### 1. Create Job
```bash
curl -X POST "http://localhost:8000/api/jobs" \
  -H "Content-Type: application/json" \
  -d '{
    "quality": "high",
    "reconstruction_type": "mesh",
    "output_formats": ["stl", "obj", "gltf"],
    "texture": true,
    "max_faces": 500000
  }'
```
Response: `{"job_id": "a1b2c3d4", "status": "pending", "message": "Job created..."}`

### 2. Upload Images
```bash
curl -X POST "http://localhost:8000/api/jobs/a1b2c3d4/upload" \
  -F "files=@photo1.jpg" \
  -F "files=@photo2.jpg" \
  -F "files=@photo3.jpg" \
  ...
```

### 3. Check Status
```bash
curl "http://localhost:8000/api/jobs/a1b2c3d4/status"
```
Response:
```json
{
  "job_id": "a1b2c3d4",
  "status": "processing",
  "progress": 0.65,
  "message": "Running Multi-View Stereo...",
  "current_step": "colmap_mvs",
  "result_files": {}
}
```

### 4. Download Results
```bash
# STL
curl "http://localhost:8000/api/jobs/a1b2c3d4/download/stl" -o model.stl

# OBJ
curl "http://localhost:8000/api/jobs/a1b2c3d4/download/obj" -o model.obj

# GLTF
curl "http://localhost:8000/api/jobs/a1b2c3d4/download/gltf" -o model.gltf
```

## Quality Presets

| Preset | Max Images | Max Image Size | COLMAP Features | Use Case |
|--------|------------|----------------|-----------------|----------|
| Low    | 50         | 1024px         | 8K              | Quick preview |
| Medium | 100        | 2048px         | 16K             | Balanced |
| High   | 200        | 4096px         | 32K             | Best quality |

## Pipeline Steps

1. **Feature Extraction** - SIFT features from all images
2. **Feature Matching** - Exhaustive matching between image pairs
3. **Sparse Reconstruction (SfM)** - Camera poses + sparse point cloud
4. **Image Undistortion** - Prepare for dense reconstruction
5. **Dense Stereo (MVS)** - Patch-match stereo for depth maps
6. **Stereo Fusion** - Fuse depth maps into dense point cloud
7. **Poisson Meshing** - Generate watertight mesh from point cloud
8. **Texture Mapping** - Project images onto mesh (optional)
9. **Export** - STL/OBJ/GLTF/PLY

## Android Integration

See `android-app/` for a ready-to-use Android client with:
- Guided photo capture (sphere overlay)
- Automatic upload to backend
- Progress polling
- Result download & sharing

## Configuration

Copy `.env.example` to `.env` and adjust:

```env
# Server
HOST=0.0.0.0
PORT=8000

# Processing
MAX_IMAGES=200
MAX_IMAGE_SIZE_MB=50
COLMAP_QUALITY=high
USE_GPU=true
GPU_DEVICE=0

# Paths
UPLOAD_DIR=/data/uploads
OUTPUT_DIR=/data/outputs
TEMP_DIR=/tmp/photogrammetry
COLMAP_PATH=colmap
```

## Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| GPU       | 4 GB VRAM | 12+ GB VRAM (RTX 3080/4080/3090/4090) |
| RAM       | 16 GB   | 32+ GB |
| Storage   | 50 GB SSD | 200+ GB NVMe |
| CPU       | 4 cores | 8+ cores |

## License

MIT License - Feel free to use commercially.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  Android    │────▶│  FastAPI     │────▶│  COLMAP +       │
│  App        │     │  Backend     │     │  Open3D         │
│  (Photos)   │     │  (Queue)     │     │  Pipeline       │
└─────────────┘     └──────────────┘     └─────────────────┘
                           │                      │
                           ▼                      ▼
                    ┌──────────────┐     ┌─────────────────┐
                    │  File        │     │  STL/OBJ/GLTF   │
                    │  Storage     │◀────│  Output         │
                    └──────────────┘     └─────────────────┘
```

## Troubleshooting

**COLMAP not found**: Install COLMAP and ensure it's in PATH, or set `COLMAP_PATH` in `.env`

**CUDA out of memory**: Reduce `QUALITY_HIGH_MAX_IMAGES` or `QUALITY_HIGH_IMAGE_SIZE`

**Slow processing**: Use GPU version, ensure `USE_GPU=true`, check `nvidia-smi`

**Poisson mesh fails**: Try lower `depth` parameter in pipeline, or increase point cloud density