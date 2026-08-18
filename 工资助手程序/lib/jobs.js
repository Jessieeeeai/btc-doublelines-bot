// 共享"作业"逻辑：AI 建议 / 派活 / 归档 / 周报。
// 供 api.js（管理员手动触发）和 netlify 定时函数（自动）共用。
const { getCol, saveCol, putKey, listPrefix, uid } = require('./store');
const C = require('./core');

function monthsAgo(n) { const d = new Date(); const x = new Date(d.getFullYear(), d.getMonth() - n, 1); return x.getFullYear() + '-' + String(x.getMonth() + 1).padStart(2, '0'); }
function curMonth() { const d = new Date(); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0'); }

// 给一个人生成"下周任务建议"，学习其最近任务 + 其 OKR；结果存 suggest/<empId>
async function suggestForEmployee(emp, allTasks, allOkrs, roles, settings) {
  const month = curMonth();
  const recent = allTasks.filter(t => t.employeeId === emp.id).slice(-15);
  const okrs = allOkrs.filter(o => o.employeeId === emp.id && o.period === month);
  const role = roles.find(r => r.name === emp.role);
  const sys = '你是团队负责人，按"目标分层"给成员拟下周工作建议。学习他过去做了什么，建议要具体、可衡量。';
  const usr = `成员：${emp.name}（${emp.role}）。\n他的本月 OKR：${okrs.length ? JSON.stringify(okrs.map(o => ({ o: o.objective, kr: (o.keyResults || []).map(k => k.text) }))) : '未设'}\n岗位常见指标：${role ? JSON.stringify(role.kpis.map(k => k.name)) : '无'}\n他最近的任务：${recent.map(t => t.title + '(' + (t.status || '') + ')').join('；') || '无记录'}\n请按"目标→3~5条可执行的下周任务（每条带一句量化指标）"输出，简洁中文，150字内。`;
  const text = await C.callAI(settings, sys, usr, false);
  await putKey('suggest/' + emp.id, { employeeId: emp.id, period: month, text, createdAt: Date.now() });
  return text;
}

async function suggestAll() {
  const settings = await C.getSettings();
  if (!settings.aiKey) return { ok: false, error: 'no ai key' };
  const [emps, tasks, roles] = await Promise.all([getCol('employees'), getCol('tasks'), getCol('roles')]);
  const okrs = await listPrefix('okr/');
  let n = 0;
  for (const e of emps.filter(x => x.active)) { try { await suggestForEmployee(e, tasks, okrs, roles, settings); n++; } catch (err) { /* skip one failure */ } }
  return { ok: true, count: n };
}

// 自动归档：早于"当前月-keep"的任务标记为已归档
async function archiveOld(keepMonths) {
  const cutoff = monthsAgo(keepMonths == null ? 2 : keepMonths);
  const tasks = await getCol('tasks');
  let n = 0;
  tasks.forEach(t => { if (t.month && t.month < cutoff && t.status !== '已归档') { t.status = '已归档'; n++; } });
  if (n) await saveCol('tasks', tasks);
  return { ok: true, archived: n };
}

// 生成本周团队周报（AI 摘要），存 digest/<month>
async function weeklyDigest() {
  const settings = await C.getSettings();
  const [emps, tasks] = await Promise.all([getCol('employees'), getCol('tasks')]);
  const month = curMonth();
  const cur = tasks.filter(t => t.month === month);
  const done = cur.filter(t => t.status === '已完成').length;
  const doing = cur.filter(t => t.status === '进行中').length;
  let summary = `本月任务 ${cur.length} 项：已完成 ${done}，进行中 ${doing}。`;
  if (settings.aiKey) {
    try {
      const byP = {};
      cur.forEach(t => { const e = emps.find(x => x.id === t.employeeId); const nm = e ? e.name : '?'; (byP[nm] = byP[nm] || []).push(t.title + '(' + t.status + ')'); });
      const usr = '请用中文写一段150字内的团队本月进展周报，点出亮点和待推进：\n' + Object.entries(byP).map(([k, v]) => k + '：' + v.join('；')).join('\n');
      summary = await C.callAI(settings, '你是团队负责人，写简洁的周报。', usr, false);
    } catch (e) {}
  }
  await putKey('digest/' + month, { month, summary, createdAt: Date.now() });
  return { ok: true, summary };
}

module.exports = { suggestForEmployee, suggestAll, archiveOld, weeklyDigest, curMonth };
