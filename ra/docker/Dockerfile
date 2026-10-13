FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends gcc-mipsel-linux-gnu binutils-mipsel-linux-gnu make python3 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
