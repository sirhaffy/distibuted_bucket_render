# Complete headless Blender Dockerfile - ALL required libraries for headless rendering
FROM python:3.10-slim

# Install COMPLETE set of system dependencies for headless Blender
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    xz-utils \
    libx11-6 \
    libxi6 \
    libxrender1 \
    libgl1-mesa-glx \
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
    libgconf-2-4 \
    libgtk-3-0 \
    libgdk-pixbuf2.0-0 \
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
RUN pip install --break-system-packages --no-cache-dir -r requirements.txt

# Download and install Blender LTS
WORKDIR /opt
RUN wget -q https://download.blender.org/release/Blender3.6/blender-3.6.8-linux-x64.tar.xz \
    && tar -xf blender-3.6.8-linux-x64.tar.xz \
    && mv blender-3.6.8-linux-x64 blender \
    && rm blender-3.6.8-linux-x64.tar.xz \
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
CMD ["python", "render_node.py"]