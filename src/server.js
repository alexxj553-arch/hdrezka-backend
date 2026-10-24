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

async function bridge(path, query = {}, method = 'GET', body) {
  const url = new URL(path, bridgeUrl);
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && String(value).length) url.searchParams.set(key, String(value));
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      method, signal: controller.signal,
      headers: { accept: 'application/json', ...(body ? { 'content-type': 'application/json' } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {})
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data.detail || data.error || `Adapter returned HTTP ${response.status}`);
      error.status = response.status >= 400 && response.status < 600 ? response.status : 502;
      throw error;
    }
    return data;
  } catch (error) {
    if (error.name === 'AbortError') {
      const e = new Error('Python adapter request timed out'); e.status = 504; throw e;
    }
    if (error.code === 'ECONNREFUSED' || error.cause?.code === 'ECONNREFUSED') {
      const e = new Error('Python adapter is unavailable. Start python_bridge first.'); e.status = 503; throw e;
    }
    throw error;
  } finally { clearTimeout(timer); }
}

app.get('/health', async (_req, res) => {
  let adapter = 'unavailable';
  let mirrors = null;
  try { const h = await bridge('/health'); adapter = 'ok'; mirrors = { active: h.active_mirror, count: h.mirror_count }; } catch {}
  res.json({ ok: true, service: 'hdrezka-backend', adapter, mirrors, timestamp: new Date().toISOString() });
});

app.get('/api/providers', (_req, res) => res.json({
  providers: [{ id: 'hdrezka', name: 'HDRezka adapter', type: 'community-library', officialApi: false,
    capabilities: ['search', 'item-details', 'translations', 'streams', 'mirror-management'] }]
}));

app.get('/api/mirrors', async (_req, res, next) => { try { res.json(await bridge('/mirrors')); } catch (e) { next(e); } });
app.post('/api/mirrors/check', async (_req, res, next) => { try { res.json(await bridge('/mirrors/check', {}, 'POST', {})); } catch (e) { next(e); } });
app.post('/api/mirrors/select', async (req, res, next) => {
  try { res.json(await bridge('/mirrors/select', {}, 'POST', { url: boundedString(req.body?.url, 'url', 300) })); }
  catch (e) { next(e); }
});
app.post('/api/mirrors/add', async (req, res, next) => {
  try { res.json(await bridge('/mirrors/add', {}, 'POST', { url: boundedString(req.body?.url, 'url', 300) })); }
  catch (e) { next(e); }
});

app.get('/api/catalog/search', async (req, res, next) => {
  try {
    const q = boundedString(req.query.q, 'q', 200);
    const limit = Math.min(30, Math.max(1, Number.parseInt(req.query.limit || '10', 10) || 10));
    res.json(await bridge('/search', { q, limit }));
  } catch (e) { next(e); }
});
for (const [route, bridgePath] of [['/api/catalog/item', '/item'], ['/api/translations', '/translations']]) {
  app.get(route, async (req, res, next) => {
    try { res.json(await bridge(bridgePath, { url: boundedString(req.query.url, 'url', 2000) })); }
    catch (e) { next(e); }
  });
}
app.get('/api/streams', async (req, res, next) => {
  try {
    const url = boundedString(req.query.url, 'url', 2000);
    const quality = req.query.quality ? boundedString(req.query.quality, 'quality', 40) : undefined;
    const translator = req.query.translator ? boundedString(req.query.translator, 'translator', 100) : undefined;
    res.json(await bridge('/streams', { url, quality, translator }));
  } catch (e) { next(e); }
});

app.use((req, res) => res.status(404).json({ error: 'Not found', path: req.path }));
app.use((error, _req, res, _next) => res.status(Number.isInteger(error.status) ? error.status : 502).json({ error: error.message || 'Request failed' }));
app.listen(port, '0.0.0.0', () => console.log(`hdrezka-backend listening on 0.0.0.0:${port}`));
