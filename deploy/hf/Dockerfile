# Onya API for a Hugging Face Docker Space.
# The build context is the staging set from scripts/deploy_hf.py:
# Dockerfile, README.md, requirements.txt, src/, data/.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY src /app/src
COPY data /app/data

# Spaces run the container as uid 1000. The app writes run traces and
# counters under /app/data/runs and /tmp, so both must be writable.
RUN mkdir -p /app/data/runs /tmp/onya-state \
    && chown -R 1000:1000 /app /tmp/onya-state

USER 1000

EXPOSE 7860

# One worker: the run store is in process memory, so polling for a run
# must always reach the same process.
CMD ["uvicorn", "api:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]
