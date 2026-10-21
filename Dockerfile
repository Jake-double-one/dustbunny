# syntax=docker/dockerfile:1

# ---- build: install Dustbunny and its dependencies into /install ----
# Everything is pure Python or ships wheels, so no compiler is needed on any platform.
FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir --root-user-action=ignore --prefix=/install .

# ---- runtime ----
FROM python:3.12-slim
ARG APP_VERSION=
ARG GIT_SHA=
LABEL org.opencontainers.image.title="Dustbunny" \
      org.opencontainers.image.description="Finds orphaned Docker appdata folders" \
      org.opencontainers.image.source="https://github.com/Jake-double-one/dustbunny" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="$APP_VERSION" \
      org.opencontainers.image.revision="$GIT_SHA"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DUSTBUNNY_VERSION=$APP_VERSION \
    DATA_DIR=/data \
    PORT=8080
COPY --from=build /install /usr/local
# uid 1000 is the usual first user on a host (and PUID of most linuxserver.io images),
# so folders of such containers are readable. See README "Folder sizes" for full access.
# /data belongs to group 0 as well (setgid, group-writable): the docker-compose.yml runs
# Dustbunny as root without any capability except reading, and such a root may only
# write where the group allows it.
RUN useradd --system --uid 1000 --user-group --home-dir /data --no-create-home dustbunny \
 && mkdir -p /data/skins \
 && chown -R dustbunny:0 /data \
 && chmod -R 2775 /data
USER dustbunny
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT', '8080'), timeout=4)"]
ENTRYPOINT ["dustbunny"]
