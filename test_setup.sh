#!/bin/bash
# Quick test script for the photogrammetry backend

echo "=== Photogrammetry Backend Test ==="
echo

# Check Python
echo "1. Python version:"
python3 --version

# Check COLMAP
echo
echo "2. COLMAP:"
if command -v colmap &> /dev/null; then
    colmap --version
else
    echo "  COLMAP not found in PATH"
fi

# Check Python packages
echo
echo "3. Python packages:"
python3 -c "
import fastapi, uvicorn, cv2, numpy, open3d, trimesh, stl, pycolmap, torch
print(f'  fastapi: {fastapi.__version__}')
print(f'  opencv: {cv2.__version__}')
print(f'  numpy: {numpy.__version__}')
print(f'  open3d: {open3d.__version__}')
print(f'  trimesh: {trimesh.__version__}')
print(f'  pycolmap: {pycolmap.__version__}')
print(f'  torch: {torch.__version__}')
print(f'  CUDA available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'  GPU: {torch.cuda.get_device_name(0)}')
"

echo
echo "=== Test Complete ==="