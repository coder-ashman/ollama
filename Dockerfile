FROM python:3.11-slim
WORKDIR /app

# System certs (good practice even offline)
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Copy wheelhouse built on the host
COPY wheels/ /wheels/
# Install without talking to PyPI
RUN pip install --no-cache-dir --no-index --find-links=/wheels flask requests gunicorn

# App
COPY app.py .
ENV PYTHONUNBUFFERED=1
EXPOSE 8089
ENV GUNICORN_CMD_ARGS="--timeout 300 -k gthread --threads 4 -w 2 -b 0.0.0.0:8089"
CMD ["gunicorn","app:app"]