FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends blender python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /worker
COPY render_worker/pyproject.toml ./
COPY render_worker/bladeforge_worker ./bladeforge_worker
COPY render_engine /render_engine
COPY public/assets/models /public/assets/models
COPY public/assets/hdri /public/assets/hdri
RUN pip3 install --break-system-packages .

RUN useradd --create-home --uid 10001 bladeforge \
    && mkdir -p /work \
    && chown -R bladeforge:bladeforge /worker /work /render_engine /public
USER bladeforge

ENV RENDER_ENGINE_PATH=/render_engine/main.py \
    RENDER_ENGINE_V2_PATH=/render_engine/v2/main.py \
    RENDER_ENGINE_VERSION=v2 \
    OUTPUT_ROOT=/work
CMD ["python3", "-m", "bladeforge_worker.main"]
