#!/bin/sh
set -eu

cd /workspace/python
exec /bin/sh -lc "./build_bundle.sh ${BUILD_BUNDLE_ARGS:-}"
