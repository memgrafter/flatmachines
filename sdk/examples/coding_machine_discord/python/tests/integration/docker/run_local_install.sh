#!/bin/sh
set -eu

ARTIFACT_DIR="${ARTIFACT_DIR:-/artifacts}"
INSTALL_DIR="${INSTALL_DIR:-/tmp/mk42-test}"

BUNDLE_FILE="$(find "${ARTIFACT_DIR}" -maxdepth 1 -type f -name 'mk42-bundle-*.tar.gz' | sort | tail -n 1)"
[ -n "${BUNDLE_FILE}" ] || {
  echo "error: no mk42 bundle found in ${ARTIFACT_DIR}" >&2
  exit 1
}

CHECKSUM_FILE="${ARTIFACT_DIR}/checksums.txt"
EXPECTED_SHA=""
if [ -f "${CHECKSUM_FILE}" ]; then
  EXPECTED_SHA="$(awk '/ mk42-bundle-.*\.tar\.gz$/ { print $1 }' "${CHECKSUM_FILE}" | tail -n 1)"
fi

set -- ./install.sh --bundle "${BUNDLE_FILE}" --yes --skip-auth-setup --dir "${INSTALL_DIR}"
if [ -n "${EXPECTED_SHA}" ]; then
  set -- "$@" --sha256 "${EXPECTED_SHA}"
fi

cd "${ARTIFACT_DIR}"
"$@"

EXPECTED_PATH_MK42="${HOME}/.local/bin/mk42"
ACTUAL_PATH_MK42="$(bash -lc 'command -v mk42' || true)"
[ -n "${ACTUAL_PATH_MK42}" ] || {
  echo "error: mk42 not found on PATH in a new login shell after install; expected ${EXPECTED_PATH_MK42}" >&2
  exit 1
}
[ "${ACTUAL_PATH_MK42}" = "${EXPECTED_PATH_MK42}" ] || {
  echo "error: mk42 resolved to ${ACTUAL_PATH_MK42}; expected ${EXPECTED_PATH_MK42}" >&2
  exit 1
}

bash -lc 'mk42 status'
"${INSTALL_DIR}/.venv/bin/python" -c "import tool_use_discord, flatagents, flatmachines; print('ok')"
