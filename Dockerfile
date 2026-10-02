FROM ghcr.io/astral-sh/uv:0.12.22@sha256:f513a91fc62fe7c17567eee97230dd198e43edb8a9fbecca843714a4358fe1bc AS uv
FROM python:3.12.15-slim-bookworm@sha256:54c85f3c47607a77f32adec749d3c81d1348bf25833671f512b26a9b6d778cb3 AS dependencies
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
FROM python:3.12.15-slim-bookworm@sha256:54c85f3c47607a77f32adec749d3c81d1348bf25833671f512b26a9b6d778cb3
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install --no-install-recommends -y libpq5=15.19-0+deb12u1 && rm -rf /var/lib/apt/lists/*
COPY --from=dependencies /app/.venv /app/.venv
RUN useradd --uid 10001 --create-home app
COPY app ./app
COPY tests ./tests
COPY start.sh ./start.sh
COPY LICENSE ./LICENSE
COPY THIRD_PARTY_NOTICES.md runtime-license-inventory.json ./
COPY licenses ./licenses
RUN chmod +x /app/start.sh
USER 10001
EXPOSE 3000
CMD ["/app/start.sh"]
