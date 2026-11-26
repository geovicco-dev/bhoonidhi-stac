# syntax=docker/dockerfile:1
# The public STAC API server: stac-fastapi-pgstac with scene counts added
# (src/bhoonidhi_stac/api). It takes the stock stac-fastapi-pgstac image's
# settings (PG*, ENABLED_EXTENSIONS, ...) and serves on port 8080 like it,
# so it can stand in for that image.
#
# Build context: the repository root. Releases are built with
# deploy/build-image.sh.
#
# Base images are pinned by digest (the tag beside each is for reading), so
# every build of a release starts from the same images.

FROM ghcr.io/astral-sh/uv:0.12.18@sha256:3adc3706091ce7c2fe595e669628caedd6d951551b92b258b7e7dbe06d9440bc AS uv

FROM python:3.12.14-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /repo
# Dependencies first, from the lock, so a code change does not re-install
# them.
COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --frozen --no-dev --extra api --no-install-project
COPY src src
RUN uv sync --frozen --no-dev --extra api --no-editable

FROM python:3.12.14-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
RUN useradd --create-home --uid 10001 app
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1
WORKDIR /app
USER app
EXPOSE 8080
CMD ["uvicorn", "bhoonidhi_stac.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
