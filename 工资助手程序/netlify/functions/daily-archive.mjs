// 每天自动：把早于"当前月-2"的任务归档
import jobs from '../../lib/jobs.js';

export default async () => {
  try { await jobs.archiveOld(2); } catch (e) { console.log('archive err', e && e.message); }
  return new Response('ok');
};

export const config = { schedule: '0 2 * * *' }; // 每天 UTC 02:00
