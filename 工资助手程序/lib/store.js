// Storage layer with two backends:
//  - Netlify (NETLIFY env present): Netlify Blobs — zero-config persistent storage
//  - Local (sandbox/dev): a single JSON file
// Both expose: getCol(name) -> array, saveCol(name, arr)

const fs = require('fs');

// Use the local JSON file ONLY when DATA_FILE is explicitly set (local dev via server.js).
// Otherwise (i.e. on Netlify) always use Netlify Blobs — the durable, persistent store.
const DATA_FILE = process.env.DATA_FILE || '';
const USE_FILE = !!DATA_FILE;

// ---------- Local JSON file backend ----------
function readFileDb() { try { return JSON.parse(fs.readFileSync(DATA_FILE, 'utf8')); } catch { return {}; } }
function writeFileDb(db) { fs.writeFileSync(DATA_FILE, JSON.stringify(db, null, 2)); }

// ---------- Netlify Blobs backend ----------
let _store = null;
async function blobStore() {
  if (!_store) {
    const { getStore } = await import('@netlify/blobs');
    _store = getStore('salary-data'); // default (eventual) consistency — fast, non-blocking reads
  }
  return _store;
}

async function getCol(name) {
  if (!USE_FILE) {
    const s = await blobStore();
    const v = await s.get(name, { type: 'json' });
    return v || [];
  }
  return readFileDb()[name] || [];
}

async function saveCol(name, arr) {
  if (!USE_FILE) {
    const s = await blobStore();
    await s.setJSON(name, arr);
    return;
  }
  const db = readFileDb();
  db[name] = arr;
  writeFileDb(db);
}

// ---------- Per-record storage (each record = its own blob key) ----------
// Used for append-heavy/concurrent data (chat messages) to avoid the
// read-modify-write race that loses data under eventual consistency.
async function putKey(key, obj) {
  if (!USE_FILE) { const s = await blobStore(); await s.setJSON(key, obj); return; }
  const db = readFileDb(); db._kv = db._kv || {}; db._kv[key] = obj; writeFileDb(db);
}
async function listPrefix(prefix) {
  if (!USE_FILE) {
    const s = await blobStore();
    const { blobs } = await s.list({ prefix });
    const out = [];
    for (const b of blobs) { const v = await s.get(b.key, { type: 'json' }); if (v) out.push(v); }
    return out;
  }
  const kv = (readFileDb()._kv) || {};
  return Object.keys(kv).filter(k => k.startsWith(prefix)).map(k => kv[k]);
}
async function delKey(key) {
  if (!USE_FILE) { const s = await blobStore(); await s.delete(key); return; }
  const db = readFileDb(); if (db._kv) delete db._kv[key]; writeFileDb(db);
}
async function getKey(key) {
  if (!USE_FILE) { const s = await blobStore(); return await s.get(key, { type: 'json' }); }
  return ((readFileDb()._kv) || {})[key] || null;
}

function uid(prefix) {
  return (prefix || 'id') + '_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
}

module.exports = { getCol, saveCol, uid, USE_FILE, putKey, listPrefix, delKey, getKey };
