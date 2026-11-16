# Builds a small image that runs the bot. Used by Render (see render.yaml).
#
# The base image is Debian with Python 3.13 and uv already installed.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

# Compile Python files during the build so the app starts faster, and copy
# packages into the image rather than linking to a cache that won't exist.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Install the dependencies first, using only the two files that list them.
# Docker caches this step, so rebuilding after a code change is quick.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Now add the code itself and install the project.
COPY README.md ./
COPY src ./src
RUN uv sync --locked --no-dev

# Don't run as root: if the app were ever compromised, the attacker would
# only have the permissions of this unprivileged user.
RUN useradd --create-home --uid 1000 app
USER app

# Inside a container the app must accept connections from outside it.
# The host sets PORT itself; 10000 is Render's default.
# LOG_FILE is empty: hosts collect what the app prints, so no file is needed.
ENV PATH="/app/.venv/bin:$PATH" \
    BIND_HOST=0.0.0.0 \
    PORT=10000 \
    LOG_FILE=""

EXPOSE 10000

CMD ["musiclink-bot"]
