#!/bin/sh
set -eu

apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates \
  curl
# Drop apt package index files after install to keep the test image small.
rm -rf /var/lib/apt/lists/*
