// Local dev server (sandbox testing). Production uses Netlify Blobs.
process.env.DATA_FILE = process.env.DATA_FILE || '/tmp/salary-data.json'; // forces file backend locally
const http = require('http');
const fs = require('fs');
const path = require('path');
const { handle } = require('./lib/api');

const PUB = path.join(__dirname, 'public');
const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json' };

const server = http.createServer((req, res) => {
  if (req.url === '/api/rpc' && req.method === 'POST') {
    let data = '';
    req.on('data', c => data += c);
    req.on('end', async () => {
      let body = {}; try { body = JSON.parse(data); } catch {}
      const token = (req.headers['authorization'] || '').replace(/^Bearer /, '');
      try {
        const r = await handle(body.action, body.params, token);
        res.writeHead(r.status, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(r.body));
      } catch (e) {
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: false, error: String(e && e.message || e) }));
      }
    });
    return;
  }
  let f = req.url.split('?')[0];
  if (f === '/') f = '/index.html';
  const fp = path.join(PUB, f);
  if (fp.startsWith(PUB) && fs.existsSync(fp)) {
    res.writeHead(200, { 'Content-Type': MIME[path.extname(fp)] || 'text/plain' });
    fs.createReadStream(fp).pipe(res);
  } else {
    res.writeHead(404); res.end('not found');
  }
});
const PORT = process.env.PORT || 3000;
server.listen(PORT, () => console.log('dev server on http://localhost:' + PORT));
