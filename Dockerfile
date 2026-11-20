# Dockerfile for Photogrammetry Backend
# Build with GPU support: docker build --target gpu -t photogrammetry-backend .

# Base stage - common dependencies
FROM ubuntu:22.04 AS base

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    git \
    wget \
    curl \
    build-essential \
    cmake \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 -s /bin/bash appuser

# Set up Python environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip
RUN /opt/venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY .env.example .env

# Create data directories
RUN mkdir -p /data/uploads /data/outputs /tmp/photogrammetry \
    && chown -R appuser:appuser /data /tmp/photogrammetry /app

USER appuser

EXPOSE 8000

CMD ["python", "-m", "app.main"]


# GPU stage - with CUDA and COLMAP GPU support
FROM nvidia/cuda:12.2-runtime-ubuntu22.04 AS gpu

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install system dependencies including COLMAP build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    git \
    wget \
    curl \
    build-essential \
    cmake \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    # COLMAP dependencies
    libsqlite3-dev \
    libglew-dev \
    libfreeimage-dev \
    libmetis-dev \
    libgflags-dev \
    libgoogle-glog-dev \
    libatlas-base-dev \
    libsuitesparse-dev \
    libeigen3-dev \
    libboost-all-dev \
    libflann-dev \
    libvtk9-dev \
    # For pycolmap
    ninja-build \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 -s /bin/bash appuser

# Set up Python environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

WORKDIR /app

# Install PyTorch with CUDA support first
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cu121

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Build and install COLMAP from source with CUDA support
RUN git clone https://github.com/colmap/colmap.git /tmp/colmap \
    && cd /tmp/colmap \
    && mkdir build && cd build \
    && cmake .. -DCUDA_ENABLED=ON -DGUI_ENABLED=OFF \
    && make -j$(nproc) \
    && make install \
    && rm -rf /tmp/colmap

# Copy application code
COPY app/ ./app/
COPY .env.example .env

# Create data directories
RUN mkdir -p /data/uploads /data/outputs /tmp/photogrammetry \
    && chown -R appuser:appuser /data /tmp/photogrammetry /app

USER appuser

EXPOSE 8000

CMD ["python", "-m", "app.main"]


# CPU-only stage (smaller, no CUDA)
FROM base AS cpu

# Install COLMAP from source (CPU only, no CUDA)
RUN mkdir -p /var/lib/apt/lists/partial \
    && apt-get update && apt-get install -y --no-install-recommends \
    git \
    cmake \
    build-essential \
    libsqlite3-dev \
    libglew-dev \
    libfreeimage-dev \
    libmetis-dev \
    libgflags-dev \
    libgoogle-glog-dev \
    libatlas-base-dev \
    libsuitesparse-dev \
    libeigen3-dev \
    libboost-all-dev \
    libflann-dev \
    ninja-build \
    && rm -rf /var/lib/apt/lists/* \
    && git clone https://github.com/colmap/colmap.git /tmp/colmap \
    && cd /tmp/colmap \
    && mkdir build && cd build \
    && cmake .. -DCUDA_ENABLED=OFF -DGUI_ENABLED=OFF \
    && make -j$(nproc) \
    && make install \
    && rm -rf /tmp/colmap

USER appuser

EXPOSE 8000

CMD ["python", "-m", "app.main"]