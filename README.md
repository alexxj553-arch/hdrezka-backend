# HDRezka Backend

REST API for an Android cinema app, built with Node.js and a small Python adapter for the community `hdrezka-api` package.

> **Status:** initial integration scaffold. The adapter is defensive because the third-party package and upstream website can change. Verify the supported methods against the installed package version before relying on stream extraction in production.

## Features

- REST API for health/provider metadata, catalog search, item details, translations, and stream links.
- Node.js API on port `8791`; Python adapter on localhost port `8792`.
- Timeouts, basic input validation, CORS configuration, Helmet headers.
- No DRM circumvention, paywall bypass, or access-control bypass.

## Requirements

- Node.js 20+
- Python 3.10+
- Access to the upstream service and compliance with its terms and applicable law.

## Run locally

### 1. Python adapter

```bash
cd python_bridge
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell:
# .venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8792
```

### 2. Node API (second terminal)

```bash
npm install
cp .env.example .env
npm start
```

On Windows, copy `.env.example` to `.env` manually if `cp` is unavailable.

### Quick checks

```bash
curl http://127.0.0.1:8791/health
curl "http://127.0.0.1:8791/api/catalog/search?q=example"
```

## API

- `GET /health` — API health and adapter connectivity.
- `GET /api/providers` — provider metadata.
- `GET /api/catalog/search?q=...&limit=10` — search.
- `GET /api/catalog/item?url=...` — fetch item details by upstream URL.
- `GET /api/translations?url=...` — available translation/voice options when supported by the adapter.
- `GET /api/streams?url=...&quality=720p&translator=...` — request stream URLs where supported by the upstream library.

Responses are JSON. Errors use `{ "error": "...", "details": "..." }`.

## Configuration

See `.env.example`. Keep the Python bridge bound to localhost unless you add authentication and network controls.

## Important notes

- This project is an integration layer, not an official HDRezka API.
- Third-party scraping libraries may stop working when upstream markup or access policies change.
- Only use content and streams you are authorized to access. Never publish credentials, cookies, or personal tokens in issues or commits.
