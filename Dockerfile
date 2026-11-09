# Hearthside: the town game (ga play) or the research viewer (ga serve) in one container.
#
#   docker build -t hearthside .
#   docker run -p 8080:8080 -v hearthside-data:/data -e HEARTHSIDE_PASSWORD=choose-one hearthside
#
# EXTRAS picks the optional dependencies: "viewer" (default; mock and hosted-API towns),
# "viewer,local-embeddings" adds sentence-transformers for free local embeddings (a large
# PyTorch download), "viewer,anthropic" or "viewer,openai" add those SDKs. See docs/deploy.md.
FROM python:3.12-slim

ARG EXTRAS=viewer
ENV PYTHONUNBUFFERED=1 UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev $(for e in $(echo "$EXTRAS" | tr ',' ' '); do printf -- '--extra %s ' "$e"; done)
COPY configs ./configs
COPY prompts ./prompts
COPY scenarios ./scenarios
COPY docs ./docs
COPY deploy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /data

ENV PATH="/app/.venv/bin:$PATH" \
    TOWN_CONFIG=configs/town_mock.yaml \
    TOWN_DIR=/data/town \
    TOWN_SPEED=normal \
    HEARTHSIDE_HOST=0.0.0.0 \
    HEARTHSIDE_PORT=8080
VOLUME ["/data"]
EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
CMD ["play"]
