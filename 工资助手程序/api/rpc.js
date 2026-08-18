const { handle } = require('../lib/api');

module.exports = async (req, res) => {
  if (req.method !== 'POST') { res.status(405).json({ ok: false, error: 'POST only' }); return; }
  let body = req.body;
  if (typeof body === 'string') { try { body = JSON.parse(body); } catch { body = {}; } }
  if (!body) body = {};
  const token = (req.headers['authorization'] || '').replace(/^Bearer /, '');
  try {
    const r = await handle(body.action, body.params, token);
    res.status(r.status).json(r.body);
  } catch (e) {
    res.status(500).json({ ok: false, error: String(e && e.message || e) });
  }
};
