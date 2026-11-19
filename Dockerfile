# SkillForge AI, hosted version: one image, one public port. See docs/hosting.md.
#
#   docker build -t skillforge .
#   docker run -p 8080:8080 -v skillforge-data:/data \
#     -e SKILLFORGE_ACCESS_TOKEN=<a long random string> -e SKILLFORGE_ALLOWED_HOSTS=localhost \
#     -e LLM_PROVIDER=gemini -e LLM_MODEL=<a model> -e GOOGLE_API_KEY=<your key> skillforge
#
# The web pages are served on $PORT (default 8080). The Python API runs inside the container on 127.0.0.1:8000 and is reached
# only through the web server, which forwards /api/* to it. Nothing secret is baked into the image: keys and the access token
# are given as environment variables (secrets) when it runs.

# ---- 1. build the web pages ------------------------------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# same-origin: the browser calls /api on the page's own address. standalone: a self-contained server folder.
# proxy: the web server sends /api/* to the Python API inside this container.
ENV NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_API_URL=same-origin \
    SKILLFORGE_STANDALONE=1 \
    SKILLFORGE_PROXY_API=http://127.0.0.1:8000
RUN npm run build

# ---- 2. the running image: Python API + the web server -----------------------------------------------------------
FROM python:3.13-slim AS app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/backend \
    SKILLFORGE_MODE=hosted \
    SKILLFORGE_DATA_DIR=/data \
    PORT=8080
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt
COPY backend/ backend/
# the web server needs only the node program, the standalone folder and the static files
COPY --from=web /usr/local/bin/node /usr/local/bin/node
COPY --from=web /web/.next/standalone /app/web
COPY --from=web /web/.next/static /app/web/.next/static
COPY deploy/start.sh /app/start.sh
RUN sed -i 's/\r$//' /app/start.sh \
    && chmod +x /app/start.sh \
    && useradd --create-home --uid 10001 skillforge \
    && mkdir -p /data && chown skillforge /data
USER skillforge
WORKDIR /app/backend
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT','8080'), timeout=4)"
CMD ["/app/start.sh"]
