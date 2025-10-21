FROM python:3.11-slim
WORKDIR /app

# System certs (good practice even offline)
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Bring in the app (and optional wheelhouse)
COPY . .

# Prefer offline installs when a wheelhouse is provided
RUN if [ -d wheels ] && [ "$(ls -A wheels)" ]; then \
        echo "Installing Python dependencies from bundled wheels"; \
        pip install --no-cache-dir --no-index --find-links=/app/wheels -r requirements.txt; \
    else \
        echo "Installing Python dependencies from PyPI"; \
        pip install --no-cache-dir -r requirements.txt; \
    fi; \
    rm -rf wheels

ENV PYTHONUNBUFFERED=1
EXPOSE 8089
ENV GUNICORN_CMD_ARGS="--timeout 300 -k gthread --threads 4 -w 2 -b 0.0.0.0:8089"
CMD ["gunicorn","app:app"]
