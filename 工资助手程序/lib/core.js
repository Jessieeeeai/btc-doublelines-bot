// Core business logic shared by the local dev server and the Vercel function.
const crypto = require('crypto');
const { getCol, saveCol, uid } = require('./store');

const SECRET = process.env.AUTH_SECRET || 'salary-helper-default-secret-change-me';
const DEFAULT_SETTINGS = {
  adminPasswordHash: sha('admin888'),
  taskWeight: 0.7,
  kpiWeight: 0.3,
  currency: '¥',
  companyName: '怦然心動 · 工资助手',
  aiBaseUrl: 'https://api.deepseek.com',
  aiModel: 'deepseek-chat',
  aiKey: ''
};

// settings safe to expose to the (admin) client — never leak secrets
function publicSettings(s) {
  return {
    companyName: s.companyName, currency: s.currency,
    taskWeight: s.taskWeight, kpiWeight: s.kpiWeight,
    aiBaseUrl: s.aiBaseUrl, aiModel: s.aiModel, aiKeySet: !!s.aiKey
  };
}

// call an OpenAI-compatible chat API (DeepSeek by default)
async function callAI(settings, system, user, wantJson) {
  if (!settings.aiKey) throw new Error('还没配置 AI 密钥：请到「设置」里填写 DeepSeek API Key');
  const base = (settings.aiBaseUrl || 'https://api.deepseek.com').replace(/\/+$/, '');
  const r = await fetch(base + '/chat/completions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + settings.aiKey },
    body: JSON.stringify({
      model: settings.aiModel || 'deepseek-chat',
      messages: [{ role: 'system', content: system }, { role: 'user', content: user }],
      temperature: 0.4,
      ...(wantJson ? { response_format: { type: 'json_object' } } : {})
    })
  });
  if (!r.ok) { const t = await r.text(); throw new Error('AI 接口错误 ' + r.status + '：' + t.slice(0, 300)); }
  const j = await r.json();
  return (j.choices && j.choices[0] && j.choices[0].message && j.choices[0].message.content) || '';
}
function extractJson(text) {
  try { return JSON.parse(text); } catch {}
  const m = text.match(/\{[\s\S]*\}/);
  if (m) { try { return JSON.parse(m[0]); } catch {} }
  return null;
}

function sha(s) { return crypto.createHash('sha256').update(String(s)).digest('hex'); }

// ---------- token ----------
function sign(payload) {
  const body = Buffer.from(JSON.stringify(payload)).toString('base64url');
  const mac = crypto.createHmac('sha256', SECRET).update(body).digest('base64url');
  return body + '.' + mac;
}
function verify(token) {
  if (!token || token.indexOf('.') < 0) return null;
  const [body, mac] = token.split('.');
  const expect = crypto.createHmac('sha256', SECRET).update(body).digest('base64url');
  if (mac !== expect) return null;
  try {
    const p = JSON.parse(Buffer.from(body, 'base64url').toString());
    if (p.exp && Date.now() > p.exp) return null;
    return p;
  } catch { return null; }
}

// ---------- settings ----------
async function getSettings() {
  const rows = await getCol('settings');
  const s = Object.assign({}, DEFAULT_SETTINGS, rows[0] || {});
  // fall back to server env var if no key saved in-app (set on Netlify)
  if (!s.aiKey && process.env.DEEPSEEK_API_KEY) s.aiKey = process.env.DEEPSEEK_API_KEY;
  if (process.env.AI_BASE_URL) s.aiBaseUrl = process.env.AI_BASE_URL;
  if (process.env.AI_MODEL) s.aiModel = process.env.AI_MODEL;
  return s;
}
async function saveSettings(s) { await saveCol('settings', [s]); }

// ---------- seed ----------
async function ensureSeed() {
  const settings = await getCol('settings');
  if (!settings[0]) await saveCol('settings', [Object.assign({}, DEFAULT_SETTINGS)]);

  const roles = await getCol('roles');
  if (!roles.length) {
    await saveCol('roles', [
      { name: '短视频', kpis: [{ name: '出片数', weight: 3, max: 10 }, { name: '按时发布率', weight: 2, max: 100 }, { name: '爆款数', weight: 2, max: 5 }] },
      { name: '剪辑', kpis: [{ name: '剪辑完成数', weight: 3, max: 15 }, { name: '审片通过率', weight: 2, max: 100 }] },
      { name: '分析师', kpis: [{ name: '胜率', weight: 3, max: 100 }, { name: '击中率', weight: 2, max: 100 }, { name: '纯盈利%', weight: 3, max: 100 }, { name: '单量', weight: 1, max: 30 }] },
      { name: '交易', kpis: [{ name: '胜率', weight: 3, max: 100 }, { name: '纯盈利%', weight: 3, max: 100 }, { name: '单量', weight: 2, max: 30 }] },
      { name: '主播', kpis: [{ name: '直播场次', weight: 3, max: 30 }, { name: '直播时长(h)', weight: 2, max: 100 }] },
      { name: '商务', kpis: [{ name: '成交商务单', weight: 3, max: 10 }, { name: '付费会员数', weight: 2, max: 50 }, { name: '返佣额', weight: 2, max: 100 }] },
      { name: '助理', kpis: [{ name: '任务按时完成率', weight: 3, max: 100 }] }
    ]);
  }

  const emps = await getCol('employees');
  if (!emps.some(e => !e.isAdmin)) {
    const mk = (name, role, baseSalary, bonusBase, commissionRate) =>
      ({ id: uid('emp'), name, role, loginCode: gencode(), baseSalary, bonusBase, commissionRate, active: true });
    await saveCol('employees', [
      mk('宋齐兴', '短视频', 6000, 3000, 0),
      mk('谢琳', '剪辑', 5000, 2000, 0),
      mk('林浩东', '分析师', 8000, 4000, 0.05),
      mk('峰哥', '分析师', 8000, 4000, 0.05),
      mk('Albee', '交易', 9000, 5000, 0.05),
      mk('Ruichen', '分析师', 7000, 3500, 0.04),
      mk('王骏', '主播', 6000, 2500, 0),
      mk('陈雨婷', '主播', 6000, 2500, 0),
      mk('koalawang', '商务', 6000, 3000, 0.1),
      mk('Jane', '助理', 5000, 1500, 0)
    ]);
  }
}
function gencode() { return Math.random().toString(36).slice(2, 6).toUpperCase() + Math.floor(Math.random() * 90 + 10); }

// ensure the admin also exists as a "person" so they have their own 工作台 (tasks/报销/工资条)
async function ensureAdminPerson() {
  const emps = await getCol('employees');
  let admin = emps.find(e => e.isAdmin);
  if (!admin) {
    admin = { id: uid('emp'), name: '郭Jessie', role: '管理', loginCode: 'BOSS' + Math.floor(Math.random() * 90 + 10), baseSalary: 0, bonusBase: 0, commissionRate: 0, active: true, isAdmin: true };
    emps.push(admin);
    await saveCol('employees', emps);
  }
  return admin;
}

// ---------- calc ----------
function calcPerf(emp, tasks, assessment, roles, settings) {
  // task score 0-100
  const myTasks = tasks.filter(t => t.employeeId === emp.id);
  let taskScore = null;
  const totPts = myTasks.reduce((a, t) => a + (Number(t.points) || 0), 0);
  if (totPts > 0) {
    const got = myTasks.reduce((a, t) => a + (t.score == null ? 0 : Number(t.score) || 0), 0);
    taskScore = Math.max(0, Math.min(100, (got / totPts) * 100));
  }
  // kpi score 0-100
  const role = roles.find(r => r.name === emp.role);
  let kpiScore = null;
  if (role && role.kpis && role.kpis.length && assessment && assessment.kpiScores) {
    let wsum = 0, acc = 0;
    role.kpis.forEach(k => {
      const v = assessment.kpiScores[k.name];
      if (v != null && v !== '') {
        const ratio = Math.max(0, Math.min(1, (Number(v) || 0) / (Number(k.max) || 1)));
        acc += ratio * (Number(k.weight) || 0);
        wsum += (Number(k.weight) || 0);
      }
    });
    if (wsum > 0) kpiScore = (acc / wsum) * 100;
  }
  // combine (renormalize if one side missing)
  const tw = settings.taskWeight, kw = settings.kpiWeight;
  let perf;
  if (taskScore != null && kpiScore != null) perf = taskScore * tw + kpiScore * kw;
  else if (taskScore != null) perf = taskScore;
  else if (kpiScore != null) perf = kpiScore;
  else perf = 0;
  if (assessment && assessment.perfOverride != null && assessment.perfOverride !== '')
    perf = Number(assessment.perfOverride);
  return {
    perfScore: Math.round(perf * 10) / 10,
    taskScore: taskScore == null ? null : Math.round(taskScore * 10) / 10,
    kpiScore: kpiScore == null ? null : Math.round(kpiScore * 10) / 10,
    taskCount: myTasks.length
  };
}

function calcSalary(emp, perfScore, assessment) {
  const a = assessment || {};
  const base = num(a.baseSalaryOverride, emp.baseSalary);     // 底薪：固定
  const perfAmount = Number(a.perfAmount) || 0;               // 绩效金额：管理员看完成情况后手动判断
  const commRate = num(a.commissionRate, emp.commissionRate);
  const businessBase = Number(a.businessBase) || 0;
  const incentive = Number(a.incentive) || 0;                // 激励/额外
  const commission = Math.round(businessBase * commRate);    // 分成：商务/交易等按需
  const total = Math.round(base + perfAmount + commission + incentive);
  return { base, perfAmount, commission, incentive, total, commRate, businessBase };
}
function num(v, d) { return (v == null || v === '') ? (Number(d) || 0) : (Number(v) || 0); }

module.exports = {
  sha, sign, verify, getSettings, saveSettings, ensureSeed, ensureAdminPerson, calcPerf, calcSalary,
  publicSettings, callAI, extractJson
};
