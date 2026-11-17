FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# CodeX.py starts the Discord client AND the FastAPI dashboard API (on a background
# thread, port API_PORT, default 8000) in one process — this is the real entrypoint.
# Note: launcher.py in this repo is dead code (imports a nonexistent main.py) and is
# not used here.
EXPOSE 8000

CMD ["python", "CodeX.py"]
