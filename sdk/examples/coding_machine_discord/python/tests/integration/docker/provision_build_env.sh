#!/bin/sh
set -eu

apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates \
  curl
# Drop apt package index files after install to keep the test image small.
rm -rf /var/lib/apt/lists/*

curl -LsSf https://astral.sh/uv/install.sh | /bin/sh
ln -sf /root/.local/bin/uv /usr/local/bin/uv
ln -sf /root/.local/bin/uvx /usr/local/bin/uvx
