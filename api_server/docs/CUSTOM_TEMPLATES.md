# Custom templates (Docker) and warm snapshots

This is **not** a full clone of E2B’s managed template builder (Dockerfile CI, global cache, edge distribution). It is a **self-hosted** pattern:

1. You register a **logical** `template_id` via `POST /templates` (the HTTP API rejects some characters such as `/` in `template_id`; use `base_image` for full refs in that flow).
2. The API stores **base image**, **container env**, **start_cmd**, and **settle_seconds**.
3. On the **first** `POST /sandboxes` with that `template_id` (Docker only), the server:
   - starts a **throwaway** build container from `base_image` with `env`;
   - runs `start_cmd` (shell, via `sh -c`);
   - sleeps `settle_seconds` (default **20**, max 600);
   - runs **`docker commit`** → stores `warm_snapshot_image` in SQLite;
   - kills the build container (no long-lived build sandbox in the DB).
4. Later sandboxes with the same `template_id` start **from that snapshot image** (plus the same `env` at create time). The expensive build runs **once per template_id** until you re-register the template (which clears the snapshot row).

## Warm pool interaction

If `SANDBOX_WARM_POOL_SIZE > 0`, after a warm snapshot exists the API starts a **separate warm-pool segment** keyed by

`(template_id, cpu_limit, memory_limit, timeout)` — the same tuple your client sends on `POST /sandboxes`.

That segment provisions **N** idle sandboxes using `from_snapshot_image=<warm_snapshot_image>`. The default pool segment (from `SANDBOX_WARM_POOL_TEMPLATE_ID`, etc.) still provisions from the **base** image when no logical template row exists.

### Auto-registration when `SANDBOX_WARM_POOL_SIZE > 0`

If `POST /sandboxes` uses a `template_id` that is **not** already in SQLite **and** is **not** exactly `SANDBOX_WARM_POOL_TEMPLATE_ID` (after env defaulting), the API **inserts** a minimal logical template: `base_image` = the usual image resolution for that id (e.g. `node:18` → `node:18`), empty `env` / `start_cmd`, `settle_seconds` 20. The next steps match registered templates: one-time warm snapshot build, then `ensure_pool_for` for `(template_id, cpu, memory, timeout)` so idle sandboxes are provisioned. This lets `my_test.py`-style clients pass a Docker image as `template_id` without calling `POST /templates` first.

## E2B comparison (precise)

- **E2B (public product):** templates are typically **built artifacts** (OCI images from Dockerfiles or their build service), versioned and distributed; warm capacity is **prepared template instances**, not arbitrary `docker commit` after an ad-hoc `start_cmd` in your API process.
- **This repo:** templates are **local SQLite + local Docker images** produced by **`docker commit`** after your `start_cmd` + settle delay. That is **similar in goal** (reuse a prepared filesystem) but **different in mechanics** and operations (no Dockerfile pipeline here, no SaaS build grid).

## API

- `POST /templates` — register or update (update clears `warm_snapshot_image` so the next sandbox triggers a rebuild).
- `GET /templates`, `GET /templates/{template_id}`.

## Limits

- **`docker commit`** captures filesystem + image metadata from the container at commit time, **not** live RAM or all dynamic process state.
- **`start_cmd` non-zero exit:** the server still settles and commits (you may want idempotent `start_cmd`); check logs.
- **Build resources:** `TEMPLATE_BUILD_CPU` / `TEMPLATE_BUILD_MEMORY` (see `config.py`) apply only to the throwaway build container.

## Example

```bash
curl -s -X POST "http://127.0.0.1:8000/templates" \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{
    "template_id": "datascience",
    "base_image": "python:3.11-slim",
    "env": {"PIP_DISABLE_PIP_VERSION_CHECK": "1"},
    "start_cmd": "pip install --no-cache-dir pandas && echo ok > /tmp/warm_ready",
    "settle_seconds": 25
  }'

# First create blocks for pull + start_cmd + settle + commit; later creates are fast.
curl -s -X POST "http://127.0.0.1:8000/sandboxes" \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"template_id": "datascience"}'
```
