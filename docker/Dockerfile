# GPU-enabled headless Blender Dockerfile with CUDA support
FROM nvidia/cuda:12.2.0-runtime-ubuntu22.04

# Install Python and system dependencies for headless Blender
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    curl \
    wget \
    xz-utils \
    libx11-6 \
    libxi6 \
    libxrender1 \
    libgl1 \
    libglu1-mesa \
    libxkbcommon0 \
    libxcursor1 \
    libxrandr2 \
    libxinerama1 \
    libsm6 \
    libice6 \
    libxext6 \
    libxfixes3 \
    libxdamage1 \
    libxcomposite1 \
    libxtst6 \
    libfontconfig1 \
    libfreetype6 \
    libasound2 \
    libgtk-3-0 \
    libgdk-pixbuf-2.0-0 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libatk1.0-0 \
    libcairo2 \
    libdrm2 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install Python packages
RUN pip3 install --no-cache-dir -r requirements.txt

# Download and install Blender 4.2 LTS
WORKDIR /opt
RUN wget -q https://download.blender.org/release/Blender4.2/blender-4.2.0-linux-x64.tar.xz \
    && tar -xf blender-4.2.0-linux-x64.tar.xz \
    && mv blender-4.2.0-linux-x64 blender \
    && rm blender-4.2.0-linux-x64.tar.xz \
    && ln -s /opt/blender/blender /usr/local/bin/blender

# Set environment for headless operation
ENV DISPLAY=""
ENV BLENDER_USER_SCRIPTS=/workspace/scripts
ENV BLENDER_USER_DATAFILES=/workspace/datafiles

# Back to app directory
WORKDIR /app

# Copy render script
COPY render_node.py .

# Create workspace
RUN mkdir -p /workspace

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run server
CMD ["python3", "render_node.py"]