# User Onboarding Plan

How Elliot moves from a developer-only codebase to something real users can
adopt. Today Elliot is consumed like a repo — clone it, install `uv` + `pnpm` +
Python 3.13 + Node 22, `make setup`, hand-edit `.env`, `make dev`. That is fine
for contributors but is not a product. This plan fixes that in four phases.

## Barriers today

1. **Toolchain** — must install uv, pnpm, Python, and Node before anything runs.
2. **Repo, not a product** — `git clone` is the install step.
3. **Manual `.env`** — must hand-edit and generate secrets.
4. **Three raw services** — `honcho start` exposes plugin/runtime/studio directly.
5. **No first-run guidance** — Studio opens to an empty dashboard.
6. **Agent wiring assumes a terminal** — `elliot connect` is CLI-only.
7. **Secrets UX** — connector auth lives in env vars; no UI to add a key.

## Phase A — One-command run (shipped)

A technical user runs Elliot with **zero toolchain install** — only Docker.

- `docker-compose.run.yml` — runs the three services from pre-built GHCR images
  (no source checkout, no local build).
- `scripts/install.sh` — `curl … | sh` bootstrap: checks Docker, downloads the
  compose file, generates a `.env` with a fresh secret key, pulls images,
  starts everything, waits for health, and opens Studio at `localhost:8080`.
- `.github/workflows/release.yml` — builds and publishes the `elliot-plugin`,
  `elliot-runtime`, and `elliot-studio` images to GHCR on every `v*` tag.
- `make run` / `make stop` — same flow for users who already have the repo.

Still open in Phase A: publish the `elliot` CLI to PyPI (`uvx elliot`) and a
thin `npx elliot-up` wrapper.

## Phase B — First-run onboarding wizard in Studio

An empty Studio guides the user to a working connector and a connected agent.

- `/welcome` route: when zero connectors exist, launch a wizard — pick a source,
  enter connection + auth in a form, auto-discover schema, pick suggested tools,
  inline lint, "Connect your agent" step, test a tool in the Playground.
- Secrets UI: add/rotate API keys, written to the encrypted `.elliot/secrets.enc`
  store — removes `.env` editing entirely.
- Ship the petstore connector pre-loaded so a new user sees working tools.
- Replace the `elliot status` CLI with a health panel in Studio.

## Phase C — Desktop app (non-technical users)

- Tauri shell bundling the three Python services as sidecar binaries plus the
  Studio static build — double-click to run, no Docker, no terminal.
- Tray icon manages service lifecycle; auto-update; signed Mac/Windows builds.

## Phase D — Registry + hosted cloud

- Connector registry: shareable catalogue, `elliot add stripe`, version pinning.
- Hosted runtime on elliot.dev: sign-up, multi-tenant isolation, a per-workspace
  hosted MCP URL — no local server. OAuth for third-party API auth; billing.
