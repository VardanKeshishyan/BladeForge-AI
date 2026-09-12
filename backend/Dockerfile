FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
RUN pip install --upgrade pip && pip install .

RUN addgroup --system bladeforge && adduser --system --ingroup bladeforge bladeforge \
    && mkdir -p /app/var/worker-output && chown -R bladeforge:bladeforge /app
USER bladeforge

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
