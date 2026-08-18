// 每周一自动：给全员推下周任务建议 + 生成团队周报
import jobs from '../../lib/jobs.js';

export default async () => {
  try { await jobs.suggestAll(); } catch (e) { console.log('suggestAll err', e && e.message); }
  try { await jobs.weeklyDigest(); } catch (e) { console.log('digest err', e && e.message); }
  return new Response('ok');
};

export const config = { schedule: '0 1 * * 1' }; // 每周一 UTC 01:00（北京约 09:00）
