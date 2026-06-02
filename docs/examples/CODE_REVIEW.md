# Code Review

## Summary
The new demo scripts can fail on a clean checkout because they install a local SDK dependency without ensuring it is built; this breaks the documented quick start flow.

## Findings

- **[P2] Build local SDK before installing dependencies** — `error_handling/js/run.sh:56-62`
  - Because this demo’s `package.json` depends on `flatagents` via `file:../../../js`, a clean clone (where `sdk/js/dist` is .gitignored) will fail to run unless the SDK is built first. The script only builds the SDK when `--local` is passed, so the default `./run.sh` path advertised in the README can hit `Cannot find module .../dist/index.js` at runtime. Consider always building the SDK (or switching to a published version) so the default quick start works on fresh checkouts.

- **[P2] Build local SDK before installing dependencies** — `writer_critic/js/run.sh:56-62`
  - This demo also installs `flatagents` from a local path, but only builds the SDK when `--local` is provided. On a fresh clone (no `sdk/js/dist`), the default `./run.sh` path will install a package missing its `dist/` entrypoints and fail at runtime. To keep the documented quick start reliable, the SDK build should happen unconditionally (or the dependency should point to a published package).
