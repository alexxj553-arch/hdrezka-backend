import 'dotenv/config';
import express from 'express';
import cors from 'cors';
import helmet from 'helmet';

const app = express();
const port = Number(process.env.PORT || 8791);
const bridgeUrl = (process.env.PYTHON_BRIDGE_URL || 'http://127.0.0.1:8792').replace(/\/$/, '');
const timeoutMs = Number(process.env.REQUEST_TIMEOUT_MS || 15000);
const corsOrigin = process.env.CORS_ORIGIN || '*';

app.disable('x-powered-by');
app.use(helmet());
app.use(cors({ origin: corsOrigin === '*' ? '*' : corsOrigin.split(',').map(s => s.trim()) }));
app.use(express.json({ limit: '256kb' }));

function boundedString(value, label, max = 2000) {
  if (typeof value !== 'string' || !value.trim()) {
    const error = new Error(`${label} is required`);
    error.status = 400;
    throw error;
  }
  const result = value.trim();
  if (result.length > max) {
    const error = new Error(`${label} is too long (max ${max} characters)`);
    error.status = 400;
    throw error;
  }
  return result;
}

async function bridge(path, query = {}) {
  const url = new URL(path, bridgeUrl);
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && String(value).length) {
      url.searchParams.set(key, String(value));
    }
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { signal: controller.signal, headers: { accept: 'application/json' } });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(body.detail || body.error || `Adapter returned HTTP ${response.status}`);
      error.status = response.status >= 400 && response.status < 600 ? response.status : 502;
      throw error;
    }
    return body;
  } catch (error) {
    if (error.name === 'AbortError') {
      const timeoutError = new Error('Python adapter request timed out');
      timeoutError.status = 504;
      throw timeoutError;
    }
    if (error.code === 'ECONNREFUSED' || error.cause?.code === 'ECONNREFUSED') {
      const unavailable = new Error('Python adapter is unavailable. Start python_bridge first.');
      unavailable.status = 503;
      throw unavailable;
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

app.get('/health', async (_req, res) => {
  let adapter = 'unavailable';
  try {
    await bridge('/health');
    adapter = 'ok';
  } catch {}
  res.json({ ok: true, service: 'hdrezka-backend', adapter, timestamp: new Date().toISOString() });
});

app.get('/api/providers', (_req, res) => {
  res.json({
    providers: [{
      id: 'hdrezka',
      name: 'HDRezka adapter',
      type: 'community-library',
      officialApi: false,
      capabilities: ['search', 'item-details', 'translations', 'streams']
    }]
  });
});

app.get('/api/catalog/search', async (req, res, next) => {
  try {
    const q = boundedString(req.query.q, 'q', 200);
    const limit = Math.min(30, Math.max(1, Number.parseInt(req.query.limit || '10', 10) || 10));
    res.json(await bridge('/search', { q, limit }));
  } catch (error) { next(error); }
});

app.get('/api/catalog/item', async (req, res, next) => {
  try {
    const url = boundedString(req.query.url, 'url', 2000);
    res.json(await bridge('/item', { url }));
  } catch (error) { next(error); }
});

app.get('/api/translations', async (req, res, next) => {
  try {
    const url = boundedString(req.query.url, 'url', 2000);
    res.json(await bridge('/translations', { url }));
  } catch (error) { next(error); }
});

app.get('/api/streams', async (req, res, next) => {
  try {
    const url = boundedString(req.query.url, 'url', 2000);
    const quality = req.query.quality ? boundedString(req.query.quality, 'quality', 40) : undefined;
    const translator = req.query.translator ? boundedString(req.query.translator, 'translator', 100) : undefined;
    res.json(await bridge('/streams', { url, quality, translator }));
  } catch (error) { next(error); }
});

app.use((req, res) => res.status(404).json({ error: 'Not found', path: req.path }));
app.use((error, _req, res, _next) => {
  const status = Number.isInteger(error.status) ? error.status : 502;
  res.status(status).json({ error: error.message || 'Request failed' });
});

app.listen(port, '0.0.0.0', () => {
  console.log(`hdrezka-backend listening on 0.0.0.0:${port}`);
});
