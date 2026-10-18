# Open Dream-RSI has zero runtime dependencies — the image is a pinned,
# non-root Python environment. The sandbox runs generated code as a
# `python -I` subprocess with a scrubbed environment and resource limits; for
# filesystem/network isolation install bubblewrap in a derived image and point
# ODR_SANDBOX_CMD at it (see README, Security model).
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY open_dream_rsi ./open_dream_rsi
RUN pip install --no-cache-dir . \
    && useradd --create-home --shell /usr/sbin/nologin odr \
    && mkdir /work && chown odr:odr /work

USER odr
WORKDIR /work

# `docker run open-dream-rsi <args>` == `python -m open_dream_rsi <args>`
ENTRYPOINT ["python", "-m", "open_dream_rsi"]
CMD ["status"]
