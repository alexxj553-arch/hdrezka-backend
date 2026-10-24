# HDRezka Backend

REST API for an Android cinema app, with a Node.js API and a Python adapter around the community `hdrezka-api` package.

> **Status:** integration scaffold; mirror management is implemented, but must be tested against the actual upstream domains and installed third-party library. A mirror responding to HTTP checks does not prove search or playback works through it.

## Features

- Search, item details, translation metadata and stream-link adapter endpoints.
- Mirror registry, parallel availability checks, active mirror selection, and adding approved mirror domains at runtime.
- HTTPS-only mirror URLs and host allowlisting.
- Node API on port 8791; Python bridge on localhost port 8792.
- No DRM circumvention or access-control bypass.

## Install

Requirements: Node.js 20+, Python 3.10+.

### Python bridge

```bash
cd python_bridge
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8792
```

### Node API (second terminal)

```bash
npm install
cp .env.example .env
npm test
npm start
```

On Windows, copy `.env.example` to `.env` manually if needed.

## Mirror API

- `GET /api/mirrors` — list known mirrors and latest check results.
- `POST /api/mirrors/check` — check all registered mirrors concurrently.
- `POST /api/mirrors/add` with JSON `{"url":"https://hdrezka.ag"}` — register and immediately check an allowlisted domain.
- `POST /api/mirrors/select` with JSON `{"url":"https://hdrezka.ag"}` — select an already registered mirror.
- `GET /health` — API and adapter status, including active mirror summary.

Example:

```bash
curl http://127.0.0.1:8791/api/mirrors
curl -X POST http://127.0.0.1:8791/api/mirrors/check
curl -X POST http://127.0.0.1:8791/api/mirrors/select -H 'Content-Type: application/json' -d '{"url":"https://hdrezka.ag"}'
```

The default allowlist is based on domains found in the inspected APK, not a claim that those domains are currently available or official. You can override `HDREZKA_ALLOWED_HOSTS`, `HDREZKA_MIRRORS`, and `HDREZKA_ACTIVE_MIRROR` in `.env`. The add/select endpoints are runtime-only; add permanent choices to environment settings and restart the bridge.

## Other API routes

- `GET /api/providers`
- `GET /api/catalog/search?q=example&limit=10`
- `GET /api/catalog/item?url=...`
- `GET /api/translations?url=...`
- `GET /api/streams?url=...&quality=720p&translator=...`

## Important limitations

- The mirror checker tests HTTPS reachability in parallel. A reachable homepage may still have broken content or playback.
- Item, translation and stream requests are rewritten to the selected mirror. Whether all methods work on a mirror depends on the installed third-party library. Search may still use the library's built-in default domain.
- This is not an official HDRezka API. Upstream markup, access policies and third-party library behavior can change.
- Only use content and streams you are authorized to access. Keep the Python bridge bound to localhost and do not expose mirror management publicly without authentication.
