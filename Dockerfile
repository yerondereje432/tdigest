FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# For AI_PROVIDER=local (free on-device semantic matching) also run:
#     pip install --no-cache-dir sentence-transformers

COPY . .

# persisted state: login session + sqlite db live in mounted volumes
ENV STATE_PATH=/app/data/tdigest.db
RUN mkdir -p /app/session /app/data
VOLUME ["/app/session", "/app/data"]

# First-time login (interactive):
#   docker run -it --rm --env-file .env \
#       -v "$PWD/session:/app/session" -v "$PWD/data:/app/data" \
#       tdigest python main.py auth
# Then run the daemon:
#   docker run -d --name tdigest --restart unless-stopped --env-file .env \
#       -v "$PWD/session:/app/session" -v "$PWD/data:/app/data" tdigest

CMD ["python", "main.py", "serve"]
