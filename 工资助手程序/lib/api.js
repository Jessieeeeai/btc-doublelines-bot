// Action dispatcher shared by local server + Vercel function.
const { getCol, saveCol, uid, putKey, listPrefix, delKey, getKey } = require('./store');
const C = require('./core');
const JOBS = require('./jobs');

const DAY = 86400000;

// 默认两张可自定义表格（列可增删改）
const DEFAULT_SHEETS = {
  tasks: { id: 'tasks', name: '任务表', visibility: 'all', columns: [
    { key: 'title', name: '任务', type: 'text' },
    { key: 'owner', name: '负责人', type: 'person' },
    { key: 'due', name: '预计完成日期', type: 'date' },
    { key: 'status', name: '进度', type: 'select', options: ['进行中', '已完成', '已归档'] },
    { key: 'dept', name: '部门', type: 'text' },
    { key: 'collab', name: '配合人员', type: 'text' },
    { key: 'note', name: '当前情况', type: 'text' }
  ] },
  kaohe: { id: 'kaohe', name: '月度考核表', visibility: 'admin', columns: [
    { key: 'person', name: '人员', type: 'person' },
    { key: 'month', name: '考核月份', type: 'text' },
    { key: 'baseWork', name: '基础工作内容', type: 'text' },
    { key: 'baseDone', name: '基础工作完成情况', type: 'text' },
    { key: 'lastImprove', name: '上月需改进的问题', type: 'text' },
    { key: 'improveStatus', name: '改进情况', type: 'text' },
    { key: 'thisImprove', name: '本月需改进', type: 'text' },
    { key: 'kpiGoal', name: '本月KPI目标', type: 'text' },
    { key: 'kpiDone', name: 'KPI完成情况', type: 'text' },
    { key: 'award', name: '本月获奖情况', type: 'text' }
  ] }
};
async function ensureSheets() {
  for (const id of Object.keys(DEFAULT_SHEETS)) {
    if (!(await getKey('sheet/' + id))) await putKey('sheet/' + id, DEFAULT_SHEETS[id]);
  }
}

async function handle(action, params, token) {
  params = params || {};
  const sess = C.verify(token);

  // ---- public ----
  if (action === 'login') {
    await C.ensureSeed();
    if (params.password != null) {
      const s = await C.getSettings();
      if (C.sha(params.password) !== s.adminPasswordHash) return err('管理员密码错误');
      const admin = await C.ensureAdminPerson();
      return ok({ token: C.sign({ role: 'admin', id: admin.id, name: admin.name, exp: Date.now() + 7 * DAY }), role: 'admin', name: admin.name });
    }
    if (params.code != null) {
      const emps = await getCol('employees');
      const e = emps.find(x => x.loginCode && x.loginCode.toUpperCase() === String(params.code).trim().toUpperCase() && x.active);
      if (!e) return err('登录码无效');
      return ok({ token: C.sign({ role: 'employee', id: e.id, name: e.name, exp: Date.now() + 7 * DAY }), role: 'employee', name: e.name });
    }
    return err('请输入密码或登录码');
  }

  if (!sess) return err('未登录或登录已过期', 401);
  if (action === 'me') return ok({ role: sess.role, name: sess.name, id: sess.id });

  // ===== 个人工作台（管理员和员工都可用，看的是“自己”的数据）=====
  if (action === 'myWorkspace') {
    const month = params.month || curMonth();
    const [emps, roles, tasksAll, asmts, expAll, annAll] = await Promise.all([
      getCol('employees'), getCol('roles'), getCol('tasks'), getCol('assessments'), getCol('expenses'), getCol('announcements')
    ]);
    let me = emps.find(e => e.id === sess.id);
    if (!me && sess.role === 'admin') me = await C.ensureAdminPerson();
    if (!me) return err('账号不存在');
    const settings = await C.getSettings();
    const tasks = tasksAll.filter(t => t.employeeId === me.id && t.month === month);
    const a = asmts.find(x => x.employeeId === me.id && x.month === month);
    const perf = C.calcPerf(me, tasks, a, roles, settings);
    const payslip = (a && a.status === 'finalized') ? C.calcSalary(me, perf.perfScore, a) : null;
    const expenses = expAll.filter(x => x.employeeId === me.id && x.month === month);
    const announcements = annAll.filter(x => x.audience === 'all' || x.audience === me.id).sort((p, q) => q.createdAt - p.createdAt);
    const okrs = (await listPrefix('okr/')).filter(o => o.employeeId === me.id && o.period === month);
    const leaves = (await listPrefix('leave/')).filter(l => l.employeeId === me.id).sort((p, q) => q.createdAt - p.createdAt);
    const myReviews = (await listPrefix('review/')).filter(r => r.fromId === me.id && r.month === month);
    const colleagues = emps.filter(e => e.active && e.id !== me.id).map(e => ({ id: e.id, name: e.name, role: e.role }));
    const suggestion = await getKey('suggest/' + me.id);
    return ok({ me: { id: me.id, name: me.name, role: me.role, isAdmin: !!me.isAdmin, baseDuties: me.baseDuties || '' }, month, tasks, perf, payslip, finalized: !!(a && a.status === 'finalized'), expenses, announcements, okrs, leaves, myReviews, colleagues, suggestion: (suggestion && suggestion.period === month) ? suggestion : null, currency: settings.currency });
  }
  // 任务自助：本人可增删改自己的任务；管理员可改任何人
  if (action === 'myTaskSave') {
    const tasks = await getCol('tasks');
    const p = params.task || {};
    if (p.id) {
      const t = tasks.find(x => x.id === p.id);
      if (!t) return err('任务不存在');
      if (sess.role !== 'admin' && t.employeeId !== sess.id) return err('无权限修改他人任务');
      ['title', 'department', 'collaborators', 'dueDate', 'status', 'note'].forEach(k => { if (k in p) t[k] = p[k]; });
      if (sess.role === 'admin' && p.employeeId) t.employeeId = p.employeeId;
    } else {
      tasks.push({ id: uid('task'), employeeId: (sess.role === 'admin' && p.employeeId) ? p.employeeId : sess.id,
        month: p.month || curMonth(), title: p.title || '', department: p.department || '', collaborators: p.collaborators || '',
        dueDate: p.dueDate || '', status: p.status || '进行中', note: p.note || '', points: 0, createdAt: Date.now(), createdBy: sess.id });
    }
    await saveCol('tasks', tasks);
    return ok({});
  }
  if (action === 'myTaskDelete') {
    let tasks = await getCol('tasks');
    const t = tasks.find(x => x.id === params.id);
    if (!t) return ok({});
    if (sess.role !== 'admin' && t.employeeId !== sess.id) return err('无权限');
    tasks = tasks.filter(x => x.id !== params.id);
    await saveCol('tasks', tasks);
    return ok({});
  }

  // 全员任务总表（所有人可看；用于共创表格）
  if (action === 'allTasks') {
    const month = params.month || curMonth();
    const [tasksAll, emps] = await Promise.all([getCol('tasks'), getCol('employees')]);
    const goals = (await listPrefix('goal/')).filter(g => g.month === month);
    return ok({ month, tasks: tasksAll.filter(t => t.month === month), employees: emps.filter(e => e.active).map(e => ({ id: e.id, name: e.name, role: e.role })), goals });
  }
  // 保存某人本月工作目标（本人或管理员）
  if (action === 'saveMonthGoal') {
    const eid = (sess.role === 'admin' && params.employeeId) ? params.employeeId : sess.id;
    await putKey('goal/' + eid + '/' + (params.month || curMonth()), { employeeId: eid, month: params.month || curMonth(), text: params.text || '' });
    return ok({});
  }

  // ===== 自定义表格（可改列、内联填、每行独立存储）=====
  if (action === 'listSheet') {
    await ensureSheets();
    const sheet = await getKey('sheet/' + params.sheetId);
    if (!sheet) return err('表不存在');
    if (sheet.visibility === 'admin' && sess.role !== 'admin') return err('无权限查看此表');
    const [records, emps] = await Promise.all([listPrefix('rec/' + params.sheetId + '/'), getCol('employees')]);
    return ok({ sheet, records, employees: emps.filter(e => e.active).map(e => ({ id: e.id, name: e.name, role: e.role })) });
  }
  if (action === 'saveCell') {
    const sheet = await getKey('sheet/' + params.sheetId);
    if (sheet && sheet.visibility === 'admin' && sess.role !== 'admin') return err('无权限');
    const key = 'rec/' + params.sheetId + '/' + params.recordId;
    const r = await getKey(key);
    if (!r) return err('记录不存在');
    r[params.key] = params.value;
    await putKey(key, r);
    return ok({});
  }
  if (action === 'addRecord') {
    const sheet = await getKey('sheet/' + params.sheetId);
    if (sheet && sheet.visibility === 'admin' && sess.role !== 'admin') return err('无权限');
    const id = uid('r');
    await putKey('rec/' + params.sheetId + '/' + id, Object.assign({ id, _createdBy: sess.id }, params.values || {}));
    return ok({ id });
  }
  if (action === 'delRecord') {
    const sheet = await getKey('sheet/' + params.sheetId);
    if (sheet && sheet.visibility === 'admin' && sess.role !== 'admin') return err('无权限');
    await delKey('rec/' + params.sheetId + '/' + params.recordId);
    return ok({});
  }
  if (action === 'saveSheetColumns') {  // 字段配置：改列（仅管理员）
    if (sess.role !== 'admin') return err('仅管理员可改表结构');
    const sheet = (await getKey('sheet/' + params.sheetId)) || { id: params.sheetId };
    if (params.columns) sheet.columns = params.columns;
    if (params.name) sheet.name = params.name;
    if (params.visibility) sheet.visibility = params.visibility;
    await putKey('sheet/' + params.sheetId, sheet);
    return ok({ sheet });
  }
  if (action === 'importSheetRecords') {  // 批量导入记录（每行独立 key）
    if (sess.role !== 'admin') return err('无权限');
    let n = 0;
    for (const v of (params.records || [])) { const id = uid('r'); await putKey('rec/' + params.sheetId + '/' + id, Object.assign({ id }, v)); n++; }
    return ok({ count: n });
  }

  // ===== 内置聊天（群组 + 消息，所有人可用）=====
  if (action === 'chatList') {
    let groups = await getCol('chatGroups');
    if (!groups.length) { groups = [{ id: 'g_all', name: '全员群', members: 'all', createdAt: Date.now() }]; await saveCol('chatGroups', groups); }
    const emps = await getCol('employees');
    const mine = groups.filter(g => g.members === 'all' || (Array.isArray(g.members) && g.members.includes(sess.id)));
    return ok({ groups: mine, employees: emps.filter(e => e.active).map(e => ({ id: e.id, name: e.name, role: e.role })) });
  }
  if (action === 'chatMessages') {
    const groups = await getCol('chatGroups');
    const g = groups.find(x => x.id === params.groupId);
    if (!g) return err('群不存在');
    if (g.members !== 'all' && !(Array.isArray(g.members) && g.members.includes(sess.id))) return err('你不在该群');
    const msgs = (await listPrefix('msg/' + params.groupId + '/')).sort((a, b) => a.createdAt - b.createdAt);
    return ok({ messages: msgs.slice(-200) });
  }
  if (action === 'chatSend') {
    const groups = await getCol('chatGroups');
    const g = groups.find(x => x.id === params.groupId);
    if (!g) return err('群不存在');
    if (g.members !== 'all' && !(Array.isArray(g.members) && g.members.includes(sess.id))) return err('你不在该群');
    const text = (params.text || '').trim();
    if (!text) return err('消息为空');
    const m = { id: uid('m'), groupId: params.groupId, senderId: sess.id, senderName: sess.name, text: text.slice(0, 2000), createdAt: Date.now() };
    await putKey('msg/' + params.groupId + '/' + m.createdAt + '_' + m.id, m);
    return ok({ message: m });
  }
  if (action === 'chatCreateGroup') {
    if (sess.role !== 'admin') return err('仅管理员可建群');
    const groups = await getCol('chatGroups');
    const g = { id: uid('g'), name: params.name || '新群组', members: params.members === 'all' ? 'all' : (params.members || []), createdAt: Date.now() };
    groups.push(g);
    await saveCol('chatGroups', groups);
    return ok({ group: g });
  }

  // ===== OKR 目标（所有人填自己的；管理员看全员）=====
  if (action === 'saveOkr') {
    const p = params.okr || {};
    const owner = (sess.role === 'admin' && p.employeeId) ? p.employeeId : sess.id;
    const id = p.id || uid('okr');
    if (p.id) { // 编辑：本人或管理员
      const existing = (await listPrefix('okr/')).find(o => o.id === p.id);
      if (existing && sess.role !== 'admin' && existing.employeeId !== sess.id) return err('无权限');
    }
    await putKey('okr/' + id, { id, employeeId: owner, period: p.period || curMonth(), objective: p.objective || '', keyResults: p.keyResults || [], createdAt: p.createdAt || Date.now() });
    return ok({ id });
  }
  if (action === 'deleteOkr') {
    const o = (await listPrefix('okr/')).find(x => x.id === params.id);
    if (o && (sess.role === 'admin' || o.employeeId === sess.id)) await delKey('okr/' + params.id);
    return ok({});
  }

  // ===== 请假/调休（员工提交，管理员审批）=====
  if (action === 'submitLeave') {
    const p = params.leave || {};
    const id = uid('lv');
    await putKey('leave/' + id, { id, employeeId: sess.id, employeeName: sess.name, type: p.type || '事假', startDate: p.startDate || '', endDate: p.endDate || '', days: Number(p.days) || 0, reason: p.reason || '', status: 'pending', createdAt: Date.now() });
    return ok({ id });
  }

  // ===== 同事互评 / 360（员工互相打分评价）=====
  if (action === 'submitReview') {
    const p = params.review || {};
    if (!p.toId) return err('请选择评价对象');
    const id = uid('rv');
    await putKey('review/' + id, { id, fromId: sess.id, fromName: sess.name, toId: p.toId, month: p.month || curMonth(), score: Number(p.score) || 0, comment: p.comment || '', createdAt: Date.now() });
    return ok({ id });
  }

  // ================= EMPLOYEE =================
  if (sess.role === 'employee') {
    const emps = await getCol('employees');
    const me = emps.find(e => e.id === sess.id);
    if (!me) return err('账号不存在');
    if (action === 'employeeHome') {
      const month = params.month || curMonth();
      const tasks = (await getCol('tasks')).filter(t => t.employeeId === me.id && t.month === month);
      const asmts = await getCol('assessments');
      const roles = await getCol('roles');
      const settings = await C.getSettings();
      const a = asmts.find(x => x.employeeId === me.id && x.month === month);
      const perf = C.calcPerf(me, tasks, a, roles, settings);
      const salary = (a && a.status === 'finalized') ? C.calcSalary(me, perf.perfScore, a) : null;
      const myExpenses = (await getCol('expenses')).filter(x => x.employeeId === me.id && x.month === month);
      const annAll = await getCol('announcements');
      const announcements = annAll.filter(x => x.audience === 'all' || x.audience === me.id).sort((a, b) => b.createdAt - a.createdAt);
      return ok({
        me: { name: me.name, role: me.role }, month, tasks, perf,
        payslip: salary, finalized: !!(a && a.status === 'finalized'), currency: settings.currency,
        expenses: myExpenses, announcements
      });
    }
    if (action === 'submitTask') {
      const tasks = await getCol('tasks');
      const t = tasks.find(x => x.id === params.taskId && x.employeeId === me.id);
      if (!t) return err('任务不存在');
      t.note = params.note || '';
      t.status = '已完成';
      t.submittedAt = Date.now();
      await saveCol('tasks', tasks);
      return ok({ task: t });
    }
    if (action === 'submitExpense') {
      const exps = await getCol('expenses');
      const p = params.expense || {};
      const e = { id: uid('exp'), employeeId: me.id, month: p.month || curMonth(),
        amount: Number(p.amount) || 0, category: p.category || '其他', note: p.note || '',
        photoUrl: p.photoUrl || '', status: 'pending', createdAt: Date.now() };
      exps.push(e);
      await saveCol('expenses', exps);
      return ok({ expense: e });
    }
    return err('无权限');
  }

  // ================= ADMIN =================
  if (sess.role !== 'admin') return err('无权限');

  if (action === 'getState') {
    const month = params.month || curMonth();
    const [employees, roles, tasksAll, asmtsAll, expAll, annAll] = await Promise.all([
      getCol('employees'), getCol('roles'), getCol('tasks'), getCol('assessments'), getCol('expenses'), getCol('announcements')
    ]);
    const settings = await C.getSettings();
    const tasks = tasksAll.filter(t => t.month === month);
    const expenses = expAll.filter(x => x.month === month);
    const payroll = employees.filter(e => e.active).map(e => {
      const a = asmtsAll.find(x => x.employeeId === e.id && x.month === month) || null;
      const perf = C.calcPerf(e, tasks, a, roles, settings);
      const salary = C.calcSalary(e, perf.perfScore, a);
      const reimburse = expenses.filter(x => x.employeeId === e.id && x.status === 'approved').reduce((s, x) => s + (Number(x.amount) || 0), 0);
      return { employee: e, assessment: a, perf, salary, reimburse, finalized: !!(a && a.status === 'finalized') };
    });
    return ok({ month, employees, roles, settings: C.publicSettings(settings), tasks, payroll, expenses, announcements: annAll });
  }

  if (action === 'trend') {
    // last 6 months totals for a person or whole team
    const [employees, roles, tasksAll, asmtsAll] = await Promise.all([
      getCol('employees'), getCol('roles'), getCol('tasks'), getCol('assessments')
    ]);
    const settings = await C.getSettings();
    const months = lastMonths(6);
    const series = months.map(m => {
      const tasks = tasksAll.filter(t => t.month === m);
      let total = 0, perfSum = 0, n = 0;
      employees.filter(e => e.active).filter(e => !params.employeeId || e.id === params.employeeId).forEach(e => {
        const a = asmtsAll.find(x => x.employeeId === e.id && x.month === m) || null;
        const perf = C.calcPerf(e, tasks, a, roles, settings);
        const salary = C.calcSalary(e, perf.perfScore, a);
        total += salary.total; perfSum += perf.perfScore; n++;
      });
      return { month: m, total, avgPerf: n ? Math.round(perfSum / n * 10) / 10 : 0 };
    });
    return ok({ series });
  }

  if (action === 'saveEmployee') {
    const emps = await getCol('employees');
    const p = params.employee;
    if (p.id) {
      const e = emps.find(x => x.id === p.id);
      if (!e) return err('员工不存在');
      Object.assign(e, p);
    } else {
      p.id = uid('emp');
      p.loginCode = p.loginCode || (Math.random().toString(36).slice(2, 6).toUpperCase() + Math.floor(Math.random() * 90 + 10));
      p.active = true;
      emps.push(p);
    }
    await saveCol('employees', emps);
    return ok({ employees: emps });
  }
  if (action === 'deleteEmployee') {
    let emps = await getCol('employees');
    const e = emps.find(x => x.id === params.id);
    if (e) e.active = false; // soft delete to keep history
    await saveCol('employees', emps);
    return ok({ employees: emps });
  }

  if (action === 'saveRoles') {
    await saveCol('roles', params.roles || []);
    return ok({ roles: params.roles });
  }

  if (action === 'saveTask') {
    const tasks = await getCol('tasks');
    const p = params.task;
    if (p.id) { const t = tasks.find(x => x.id === p.id); if (t) Object.assign(t, p); }
    else {
      p.id = uid('task'); p.status = p.status || '进行中'; p.createdAt = Date.now();
      p.month = p.month || curMonth();
      tasks.push(p);
    }
    await saveCol('tasks', tasks);
    return ok({ task: p });
  }
  if (action === 'scoreTask') {
    const tasks = await getCol('tasks');
    const t = tasks.find(x => x.id === params.id);
    if (!t) return err('任务不存在');
    t.score = params.score; t.scored = true;
    await saveCol('tasks', tasks);
    return ok({ task: t });
  }
  if (action === 'deleteTask') {
    let tasks = await getCol('tasks');
    tasks = tasks.filter(x => x.id !== params.id);
    await saveCol('tasks', tasks);
    return ok({});
  }

  if (action === 'saveAssessment') {
    const asmts = await getCol('assessments');
    const p = params.assessment;
    let a = asmts.find(x => x.employeeId === p.employeeId && x.month === p.month);
    if (!a) { a = { id: uid('as'), status: 'draft' }; asmts.push(a); }
    Object.assign(a, p);
    if (!a.status) a.status = 'draft';
    await saveCol('assessments', asmts);
    return ok({ assessment: a });
  }
  if (action === 'finalizeAssessment') {
    const asmts = await getCol('assessments');
    const a = asmts.find(x => x.employeeId === params.employeeId && x.month === params.month);
    if (!a) return err('请先保存考核数据');
    a.status = params.unfinalize ? 'draft' : 'finalized';
    a.finalizedAt = Date.now();
    await saveCol('assessments', asmts);
    return ok({ assessment: a });
  }

  if (action === 'saveSettings') {
    const s = await C.getSettings();
    Object.assign(s, params.settings);
    await C.saveSettings(s);
    return ok({ settings: s });
  }
  if (action === 'changePassword') {
    const s = await C.getSettings();
    s.adminPasswordHash = C.sha(params.password);
    await C.saveSettings(s);
    return ok({});
  }

  // ---- 报销审批 ----
  if (action === 'approveExpense') {
    const exps = await getCol('expenses');
    const e = exps.find(x => x.id === params.id);
    if (!e) return err('报销单不存在');
    e.status = params.approve ? 'approved' : 'rejected';
    e.decidedNote = params.note || '';
    e.decidedAt = Date.now();
    await saveCol('expenses', exps);
    return ok({ expense: e });
  }

  // ---- 公告 / 通知 ----
  if (action === 'postAnnouncement') {
    const anns = await getCol('announcements');
    const p = params.announcement || {};
    const a = { id: uid('ann'), title: p.title || '', body: p.body || '', audience: p.audience || 'all', createdAt: Date.now() };
    anns.push(a);
    await saveCol('announcements', anns);
    return ok({ announcement: a });
  }
  if (action === 'deleteAnnouncement') {
    let anns = await getCol('announcements');
    anns = anns.filter(x => x.id !== params.id);
    await saveCol('announcements', anns);
    return ok({});
  }

  // ---- AI 能力 ----
  if (action === 'aiSplitKpi') {
    const settings = await C.getSettings();
    const emps = await getCol('employees');
    const roles = await getCol('roles');
    const e = emps.find(x => x.id === params.employeeId);
    if (!e) return err('员工不存在');
    const role = roles.find(r => r.name === e.role);
    const sys = '你是一名资深的内容/交易自媒体团队负责人，擅长把月度目标拆解成可量化的 KPI 和具体任务。只输出 JSON。';
    const usr = `员工：${e.name}，岗位：${e.role}。\n该岗位的考核指标模板：${role ? JSON.stringify(role.kpis) : '无'}。\n本月目标：${params.goal || '（未填，请按岗位常规拟定）'}。\n请拆解出本月 3~6 个具体任务，每个任务给一个合理分值(points，整数，合计约100)。\n用如下 JSON 输出：{"summary":"一句话说明本月重点","tasks":[{"title":"任务标题","desc":"简短说明","points":数字}]}`;
    const out = await C.callAI(settings, sys, usr, true);
    const data = C.extractJson(out) || { summary: out, tasks: [] };
    return ok({ result: data });
  }
  if (action === 'aiReview') {
    const settings = await C.getSettings();
    const [emps, roles, tasksAll, asmts] = await Promise.all([getCol('employees'), getCol('roles'), getCol('tasks'), getCol('assessments')]);
    const e = emps.find(x => x.id === params.employeeId);
    if (!e) return err('员工不存在');
    const role = roles.find(r => r.name === e.role);
    const tasks = tasksAll.filter(t => t.employeeId === e.id && t.month === params.month);
    const a = asmts.find(x => x.employeeId === e.id && x.month === params.month);
    const sys = '你是 HR 绩效顾问。管理员会根据完成情况手动决定“绩效金额”。你的任务是基于事实给出客观建议，帮管理员判断，不要夸大。';
    const usr = `员工：${e.name}（${e.role}），底薪 ${e.baseSalary} 元（绩效金额通常在底薪的 0%~50% 之间浮动，供你参考量级）。\n本月任务及完成情况：\n${tasks.map(t => `- ${t.title} 完成情况：${t.note || '未填写'}`).join('\n') || '无任务'}\nKPI/完成补充：${a ? JSON.stringify(a.kpiScores || {}) : '无'}\n请给出：1) 整体完成度评价（好/中/差及原因）；2) 建议的本月绩效金额区间（给个数字范围，并说明理由）。控制在 200 字内。最终金额由管理员决定。`;
    const out = await C.callAI(settings, sys, usr, false);
    return ok({ result: out });
  }
  if (action === 'aiComment') {
    const settings = await C.getSettings();
    const [emps, roles, tasksAll, asmts] = await Promise.all([getCol('employees'), getCol('roles'), getCol('tasks'), getCol('assessments')]);
    const e = emps.find(x => x.id === params.employeeId);
    if (!e) return err('员工不存在');
    const tasks = tasksAll.filter(t => t.employeeId === e.id && t.month === params.month);
    const a = asmts.find(x => x.employeeId === e.id && x.month === params.month);
    const perf = C.calcPerf(e, tasks, a, roles, settings);
    const sys = '你是一位温暖而专业的团队主管，给员工写月度绩效评语。语气真诚、具体、对事不对人，先肯定再给改进建议。';
    const usr = `员工：${e.name}（${e.role}），本月绩效分 ${perf.perfScore}/100。\n任务完成：\n${tasks.map(t => `- ${t.title}：${t.note || '未填写'}（${t.score ?? '?'}/${t.points}）`).join('\n') || '无'}\n请写一段 100~150 字的中文绩效评语，包含亮点和下月改进方向。`;
    const out = await C.callAI(settings, sys, usr, false);
    return ok({ result: out });
  }

  // 全员 OKR（管理员）
  if (action === 'listOkrs') {
    const period = params.period || curMonth();
    const okrs = (await listPrefix('okr/')).filter(o => o.period === period);
    return ok({ okrs });
  }
  // 全部请假单（管理员审批）
  if (action === 'listLeaves') {
    const leaves = (await listPrefix('leave/')).sort((a, b) => b.createdAt - a.createdAt);
    return ok({ leaves });
  }
  if (action === 'approveLeave') {
    const l = (await listPrefix('leave/')).find(x => x.id === params.id);
    if (!l) return err('请假单不存在');
    l.status = params.approve ? 'approved' : 'rejected';
    l.decidedNote = params.note || ''; l.decidedAt = Date.now();
    await putKey('leave/' + l.id, l);
    return ok({ leave: l });
  }
  // 某员工收到的互评（核算/360 用）
  if (action === 'reviewsFor') {
    const rv = (await listPrefix('review/')).filter(r => r.toId === params.employeeId && (!params.month || r.month === params.month));
    return ok({ reviews: rv });
  }

  // === AI 自动化（管理员手动触发；定时函数自动跑同样的逻辑）===
  if (action === 'aiSplitObjective') {  // 写一个目标 → AI 拆 KR
    const settings = await C.getSettings();
    const sys = '你是 OKR 教练。把一个目标(Objective)拆成 3~4 个可衡量的关键结果(KR)，每个 KR 带一个量化指标。只输出 JSON。';
    const usr = `目标：${params.objective}\n输出格式：{"krs":[{"text":"关键结果","metric":"量化指标"}]}`;
    const out = await C.callAI(settings, sys, usr, true);
    return ok({ result: C.extractJson(out) || { krs: [] } });
  }
  if (action === 'aiSuggestAll') { return ok(await JOBS.suggestAll()); }   // 给全员推下周建议
  if (action === 'archiveNow') { return ok(await JOBS.archiveOld(params.keepMonths)); }
  if (action === 'weeklyDigest') { return ok(await JOBS.weeklyDigest()); }
  if (action === 'getDigest') { const month = params.month || curMonth(); return ok({ digest: await getKey('digest/' + month) }); }
  if (action === 'aiAssign') {   // AI 按擅长把一批任务分配到人并创建
    const settings = await C.getSettings();
    const emps = (await getCol('employees')).filter(e => e.active);
    const titles = (params.tasksText || '').split('\n').map(s => s.trim()).filter(Boolean);
    if (!titles.length) return err('请输入任务（每行一条）');
    const sys = '你是项目经理，按每个成员的擅长把任务分配给最合适的人。只输出 JSON。';
    const usr = `成员及擅长：\n${emps.map(e => `${e.name}（${e.role}）擅长：${e.skills || '未填'}`).join('\n')}\n待分配任务：\n${titles.map((t, i) => (i + 1) + '. ' + t).join('\n')}\n输出：{"assign":[{"task":"任务原文","owner":"成员姓名"}]}`;
    const out = await C.callAI(settings, sys, usr, true);
    const data = C.extractJson(out) || { assign: [] };
    const month = params.month || curMonth();
    const tasks = await getCol('tasks');
    let n = 0;
    (data.assign || []).forEach(a => {
      const e = emps.find(x => x.name === a.owner) || emps[0];
      if (!e) return;
      tasks.push({ id: uid('task'), employeeId: e.id, month, title: a.task, department: '', collaborators: '', dueDate: month + '-28', status: '进行中', note: 'AI按擅长分配', points: 0, createdAt: Date.now() });
      n++;
    });
    await saveCol('tasks', tasks);
    return ok({ count: n, assign: data.assign || [] });
  }

  // 某员工在指定月份们的任务（核算弹窗用：本月+上月上下文）
  if (action === 'empTasks') {
    const all = await getCol('tasks');
    const months = params.months || [];
    const res = {};
    for (const m of months) res[m] = all.filter(t => t.employeeId === params.employeeId && t.month === m);
    return ok({ tasks: res });
  }

  // 一次性原子导入月度考核（每人每月的结构化字段，一次读一次写）
  if (action === 'importAssessments') {
    const asmts = await getCol('assessments');
    (params.assessments || []).forEach(p => {
      let a = asmts.find(x => x.employeeId === p.employeeId && x.month === p.month);
      if (!a) { a = { id: uid('as'), status: 'draft' }; asmts.push(a); }
      Object.assign(a, p);
    });
    await saveCol('assessments', asmts);
    return ok({ count: (params.assessments || []).length });
  }

  // 一次性原子导入/覆盖任务（一次读一次写，避免逐条写的最终一致竞态丢数据）
  if (action === 'importTasks') {
    const incoming = (params.tasks || []).map(t => ({
      id: uid('task'), status: t.status || '进行中', points: Number(t.points) || 0,
      createdAt: Date.now(), department: t.department || '', collaborators: t.collaborators || '',
      dueDate: t.dueDate || '', note: t.note || '', employeeId: t.employeeId, month: t.month, title: t.title || ''
    }));
    if (params.replace) {
      await saveCol('tasks', incoming);
    } else {
      const cur = await getCol('tasks');
      await saveCol('tasks', cur.concat(incoming));
    }
    return ok({ count: incoming.length });
  }

  return err('未知操作: ' + action);
}

function curMonth() { const d = new Date(); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0'); }
function lastMonths(n) {
  const out = []; const d = new Date();
  for (let i = n - 1; i >= 0; i--) {
    const x = new Date(d.getFullYear(), d.getMonth() - i, 1);
    out.push(x.getFullYear() + '-' + String(x.getMonth() + 1).padStart(2, '0'));
  }
  return out;
}
function ok(data) { return { status: 200, body: Object.assign({ ok: true }, data) }; }
function err(msg, code) { return { status: code || 400, body: { ok: false, error: msg } }; }

module.exports = { handle };
