# Blender Cloud Renderer

![Python](https://img.shields.io/badge/Python-3.10-blue?logo=python&logoColor=white)
![Blender](https://img.shields.io/badge/Blender-4.2-orange?logo=blender&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![Azure](https://img.shields.io/badge/Azure-Container%20Instances-0078D4?logo=microsoftazure&logoColor=white)
![Status](https://img.shields.io/badge/Status-WIP-yellow)

Blender addon that splits a frame into buckets, sends them to Docker containers for rendering, and composites the results progressively as EXR MultiLayer tiles. Think Cinema 4D Team Render, but for Blender and cloud infrastructure.

> **Status:** Work in progress. Bucket splitting, Docker containers, EXR output, and live preview all work locally. Azure deployment not yet done.

## Why

Blender only renders on the machine it's running on. I wanted to offload heavy renders to the cloud while still getting visual feedback as buckets complete - not just wait for the entire frame. The end goal is rendering at 16K on Azure while keeping the creative loop tight.

## Features

- **Square bucket grid** - configurable NxN grid (1-16), center-out render order
- **Camera selector** - pick any camera in the scene from a dropdown
- **Render region support** - respects Blender's render border, only renders visible area
- **EXR MultiLayer output** - all render passes preserved (Combined, Depth, Normal, etc.), DWAA compression, 32-bit float
- **Live preview** - opens Image Editor and shows buckets appearing as they complete
- **Save Final** - exports assembled render to disk as timestamped EXR
- **Stateless containers** - nothing persists after a job, works anywhere (Docker, ACI, K8s)

## How it works

```
Blender Addon
├── Splits frame into NxN bucket grid (center-out order)
├── Packs .blend + assets into temp file
├── Uploads .blend to each container via HTTP POST /upload
├── Starts render jobs via POST /render/start (one bucket per container)
│   (sends camera name, bucket region, EXR settings)
├── Polls GET /render/progress/{job_id} until complete
├── Downloads finished bucket EXR via GET /render/result/{job_id}
│   (container deletes the file after download)
├── Composites Combined pass pixels into live preview image
└── Calls DELETE /cleanup/all when done
```

Containers are fully stateless - nothing persists after a job completes. Works the same whether the container runs locally via Docker Compose, in Azure Container Instances, or in Kubernetes.

## Structure

```
__init__.py               Addon entry point, property registration
addon_preferences.py      User preferences

core/
  bucket_splitter.py      Frame → grid of render regions
  render_cordinator.py    Job queue, distributes buckets to containers
  docker_manager.py       Container lifecycle (start, stop, health)
  image_compositor.py     Stitches buckets into final EXR
  scene_packer.py         Packs .blend + dependencies for transfer

docker/
  Dockerfile              Headless Blender 3.6.8 render environment
  render_node.py          Flask HTTP server inside each container
  requirements.txt        Python dependencies for containers

operators/
  render_operator.py      Start/Stop render, Pack Scene, Save Final
  assembly_operators.py   Assembly engine operators
  assembly_preview.py     Preview Assembly operator
  bucket_manager.py       Bucket management utilities
  docker_operator.py      Docker debug operator

panels/
  render_panel.py         UI panel in Render Properties

utils/
  file_utils.py           File I/O helpers
  logging_utils.py        Logging utilities
  network_utils.py        HTTP communication with containers
```

## Stack

- **Host:** Python 3.10, Blender 4.2 API, NumPy
- **Containers:** Blender 3.6.8 headless, Flask, Python 3.10
- **Infra:** Docker Compose (local), Azure Container Instances (planned)
- **Output:** OpenEXR MultiLayer (DWAA, 32-bit float)

## What works

- Square bucket grid with configurable size (NxN)
- Center-out render order (starts from middle, spirals outward)
- Camera selection from scene
- Render region support (only renders visible area)
- EXR MultiLayer output with all passes from containers
- Docker containers build and run (4 nodes on ports 8080-8083)
- Stateless HTTP communication (upload, render, download, cleanup)
- Live preview in Image Editor as buckets complete
- Save Final button exports assembled render as timestamped EXR

## What doesn't work yet

- GPU rendering in Docker (no NVIDIA Container Toolkit, containers use CPU)
- No Azure deployment
- No per-bucket progress feedback (only completion notification)
- No auth on container API (fine for local, needs fixing for cloud)
- Assembly of individual EXR passes (only Combined pass composited in live preview)

## Running locally

```bash
docker compose up --build -d
```

Verify containers are running:

```bash
docker ps
```

Install in Blender: zip this folder, then Edit > Preferences > Add-ons > Install from Disk. Enable "Distributed Render". The panel shows up in Render Properties (camera icon).

Zip command to create the addon package:

```sh
zip -r distibuted_bucket_render.zip distibuted_bucket_render/ \
  -x "*.blend1" "*.zip" \
  "distibuted_bucket_render/bucket_resources/*" \
  "distibuted_bucket_render/BlenderTestScene/*" \
  "*/__pycache__/*" \
  "distibuted_bucket_render/.git/*" \
  "distibuted_bucket_render/.idea/*"
```

## Container API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| POST | `/upload` | Upload .blend file |
| POST | `/render/start` | Start render job (JSON body with camera, region, format) |
| GET | `/render/progress/{id}` | Poll job progress |
| GET | `/render/result/{id}` | Download rendered EXR (auto-deletes after) |
| DELETE | `/cleanup/all` | Remove all temp files |

## Next steps

- Per-bucket progress feedback (update at 25%, 50%, 75%)
- Deploy to Azure Container Instances
- GPU container support (NVIDIA Container Toolkit)
- Auth/TLS on container API for cloud deployment
- Full EXR pass assembly (merge all passes from all buckets into one file)
- Evaluate Kubernetes for better scaling and management in cloud environments
