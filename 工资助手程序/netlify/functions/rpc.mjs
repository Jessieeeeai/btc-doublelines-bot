import api from '../../lib/api.js';

export default async (req) => {
  if (req.method !== 'POST') return json({ ok: false, error: 'POST only' }, 405);
  let body = {};
  try { body = await req.json(); } catch {}
  const token = (req.headers.get('authorization') || '').replace(/^Bearer /, '');
  try {
    const r = await api.handle(body.action, body.params, token);
    return json(r.body, r.status);
  } catch (e) {
    return json({ ok: false, error: String((e && e.message) || e) }, 500);
  }
};

function json(obj, status) {
  return new Response(JSON.stringify(obj), { status: status || 200, headers: { 'Content-Type': 'application/json' } });
}

export const config = { path: '/api/rpc' };
