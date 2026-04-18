# Docker-backed Debian integration tests

These tests are opt-in and meant for progressive dependency discovery.

Discovered host requirements should be encoded into the Docker provisioning scripts, not supplied ad hoc at runtime.

Current provisioning files:

- `docker/provision_build_env.sh`
- `docker/provision_run_env.sh`

## Run

Docker-backed tests in `tests/integration` run by default.

```bash
cd python
./.venv/bin/python -m pytest tests/integration
```

or via the test runner:

```bash
cd python
./test.sh tests/integration
```

To skip them explicitly:

```bash
cd python
./test.sh tests/integration --skip-docker-integration
```

or:

```bash
export SKIP_DOCKER_INTEGRATION=1
```

## Optional knobs

Build command args only:

```bash
export MK42_DEBIAN_BUILD_ARGS="..."
```

Alternate install target only:

```bash
export MK42_DEBIAN_INSTALL_DIR="/tmp/mk42-test"
```

When a new dependency is discovered, update the Docker provisioning scripts and docs together.
