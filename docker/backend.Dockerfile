FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY . .

# DB target comes from compose (postgresql://...) or local default (sqlite)
RUN chmod +x scripts/bootstrap.sh
EXPOSE 8000
CMD ["bash", "scripts/bootstrap.sh"]
