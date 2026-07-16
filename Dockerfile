# =============================================================================
# LiteLLM Proxy – Custom Image with Config Bundled
# =============================================================================
# Use this if you want a self-contained image. Otherwise, use the official
# image and mount config.yaml at runtime (see docker-compose.yaml).
#
# ⚠️ The bundled config.yaml contains your REAL API keys in plain text.
# Never push this image to a public/shared registry.
#
# Usage:
#   docker build -t litellm-free-models .
#   docker run -p 4000:4000 --env-file .env litellm-free-models
# =============================================================================

FROM ghcr.io/berriai/litellm:v1.92.0 AS base

# Copy config
COPY config.yaml /app/config.yaml

EXPOSE 4000

ENTRYPOINT ["litellm"]
CMD ["--config", "/app/config.yaml", "--port", "4000"]
