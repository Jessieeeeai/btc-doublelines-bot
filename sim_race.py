"""三年期赛马回测: 忠实复刻 signal_bot_race.py 语义 + 三个新开关 (cap / timestop / width)"""
import json
from signals import detect_signals
from backtest import _compute_ema, _compute_adx

COMMON = dict(body_ratio=0.5, entanglement_tolerance=0.005, sl_buffer_pct=0.02,
              entry_wait_bars=3, regime_adx_high=25, regime_ema_dist_trend=0.02)

STRATS = {
    'A': dict(tp_r=2.0, stair=False, cooldown=False, da=False, kelly=False, pyramid=False),
    'B': dict(tp_r=8.0, stair=True,  cooldown=True,  da=False, kelly=False, pyramid=False),
    'C': dict(tp_r=8.0, stair=True,  cooldown=True,  da=True,  kelly=True,  pyramid=True),
}

def f6_ok(bars, sig, ema200, adx):
    i = sig['index']; close = bars[i]['close']; ev = ema200[i]
    if ev is None or ev <= 0: return False
    dist = abs(close - ev) / ev
    if adx[i] is not None and adx[i] > COMMON['regime_adx_high'] and dist > COMMON['regime_ema_dist_trend']:
        return False
    return close > ev if sig['direction'] == 'long' else close < ev

def width30(bars, i):
    j0 = max(0, i - 720)
    lo = min(b['low'] for b in bars[j0:i+1]); hi = max(b['high'] for b in bars[j0:i+1])
    return (hi - lo) / lo * 100

def run(bars, code, cap=999, ts_days=999, width_T=0.0, t_start=None, t_end=None):
    cfg = STRATS[code]
    ema200 = _compute_ema(bars, 200)
    adx = _compute_adx(bars, 14)
    raw = detect_signals(bars, COMMON['body_ratio'], COMMON['entanglement_tolerance'])
    raw = [s for s in raw if s['index'] < len(bars) - 1 and bars[s['index']]['ts'] % 3600 == 0]
    if t_start: raw = [s for s in raw if bars[s['index']]['ts'] >= t_start]
    if t_end:   raw = [s for s in raw if bars[s['index']]['ts'] <= t_end]
    raw = [s for s in raw if s['index'] >= 720]
    raw = [s for s in raw if f6_ok(bars, s, ema200, adx)]
    raw.sort(key=lambda s: s['index'])

    trades = []      # completed, chronological-by-formation (list order, like the bot's state list)
    open_pos = []    # (dir, entry_ts, ref to trade dict)
    pause = {'all': 0, 'long': 0, 'short': 0}
    skipped = dict(cooldown=0, cap=0, width=0)

    def kelly_size(sig_ts):
        comp = [t for t in trades if t['exit_ts'] is not None and t['exit_ts'] <= sig_ts]
        rec = comp[-3:]
        if len(rec) >= 3 and all(t['raw'] > 0 for t in rec): return 2.0
        if len(rec) >= 2 and all(t['raw'] > 0 for t in rec[-2:]): return 1.5
        if rec and rec[-1]['raw'] < 0: return 0.7
        return 1.0

    for sig in raw:
        i = sig['index']; d = sig['direction']; sts = bars[i]['ts']
        if cfg['cooldown']:
            p = pause[d] if cfg['da'] else pause['all']
            if sts < p: skipped['cooldown'] += 1; continue
        if width_T and width30(bars, i) < width_T:
            skipped['width'] += 1; continue
        # geometry
        if d == 'long':
            ext = min(sig['B_low'], sig['C_low']); sl0 = ext * (1 - COMMON['sl_buffer_pct'])
            trig = max(sig['B_close'], sig['C_close'])
        else:
            ext = max(sig['B_high'], sig['C_high']); sl0 = ext * (1 + COMMON['sl_buffer_pct'])
            trig = min(sig['B_close'], sig['C_close'])
        r = abs(trig - sl0)
        if r <= 0: continue
        tp = trig + cfg['tp_r'] * r if d == 'long' else trig - cfg['tp_r'] * r
        expires = sts + (COMMON['entry_wait_bars'] + 1) * 3600
        size = kelly_size(sts) if cfg['kelly'] else 1.0

        # ---- waiting phase ----
        entry_ts = None
        j = i + 1
        while j < len(bars):
            b = bars[j]
            if b['ts'] > expires: break
            if d == 'long':
                if b['low'] <= sl0: break            # invalidated
                if b['high'] >= trig: entry_ts = b['ts']; break
            else:
                if b['high'] >= sl0: break
                if b['low'] <= trig: entry_ts = b['ts']; break
            j += 1
        if entry_ts is None: continue

        # cap check at entry moment (count same-dir open among entered)
        n_open = sum(1 for od, oe, ot in open_pos if od == d and ot['exit_ts'] is None or
                     (od == d and ot['exit_ts'] is not None and ot['exit_ts'] > entry_ts and oe <= entry_ts))
        n_open = sum(1 for od, oe, ot in open_pos
                     if od == d and oe <= entry_ts and (ot['exit_ts'] is None or ot['exit_ts'] > entry_ts))
        if n_open >= cap:
            skipped['cap'] += 1; continue

        # ---- position phase ----
        entry = trig; sl = sl0
        s2 = s4 = pyr = False; pyr_px = None
        lvl1 = entry + r if d == 'long' else entry - r
        lvl2 = entry + 2*r if d == 'long' else entry - 2*r
        lvl4 = entry + 4*r if d == 'long' else entry - 4*r
        cutoff = entry_ts + ts_days * 86400
        exit_ts = exit_px = None; reason = None
        s2t = False  # 2R ever touched (incremental)
        k = j + 1
        while k < len(bars):
            b = bars[k]
            if not s2t and ((d == 'long' and b['high'] >= lvl2) or (d == 'short' and b['low'] <= lvl2)):
                s2t = True
            # time stop: at first bar CLOSE beyond cutoff, if 2R never touched
            if b['ts'] + 3600 > cutoff and not s2t:
                exit_ts = b['ts']; exit_px = b['close']; reason = 'time'; break
            # stairs
            if cfg['stair']:
                if d == 'long':
                    if not s2 and b['high'] >= lvl2:
                        ns = entry + r
                        if ns > sl: sl = ns
                        s2 = True
                    if not s4 and b['high'] >= lvl4:
                        ns = entry + 2*r
                        if ns > sl: sl = ns
                        s4 = True
                else:
                    if not s2 and b['low'] <= lvl2:
                        ns = entry - r
                        if ns < sl: sl = ns
                        s2 = True
                    if not s4 and b['low'] <= lvl4:
                        ns = entry - 2*r
                        if ns < sl: sl = ns
                        s4 = True
            if cfg['pyramid'] and not pyr:
                if (d == 'long' and b['high'] >= lvl1) or (d == 'short' and b['low'] <= lvl1):
                    pyr = True; pyr_px = lvl1
            # exits (SL first)
            if d == 'long':
                if b['low'] <= sl: exit_ts, exit_px, reason = b['ts'], sl, 'sl'; break
                if b['high'] >= tp: exit_ts, exit_px, reason = b['ts'], tp, 'tp'; break
            else:
                if b['high'] >= sl: exit_ts, exit_px, reason = b['ts'], sl, 'sl'; break
                if b['low'] <= tp: exit_ts, exit_px, reason = b['ts'], tp, 'tp'; break
            k += 1

        t = dict(sig_ts=sts, dir=d, entry=entry, entry_ts=entry_ts, r=r, size=size,
                 exit_ts=exit_ts, exit_px=exit_px, reason=reason, raw=None, sized=None,
                 pyr=pyr, s2=s2)
        if exit_ts is not None:
            main = (exit_px - entry) / r if d == 'long' else (entry - exit_px) / r
            p = 0.0
            if pyr: p = 0.5 * ((exit_px - pyr_px) / r if d == 'long' else (pyr_px - exit_px) / r)
            t['raw'] = round(main + p, 3); t['sized'] = round((main + p) * size, 3)
            # cooldown update
            if cfg['cooldown'] and t['raw'] < 0:
                comp = [x for x in trades if x['exit_ts'] is not None and x['exit_ts'] <= exit_ts] + [t]
                rec = comp[-2:]
                if len(rec) == 2 and all(x['raw'] < 0 for x in rec):
                    key = d if cfg['da'] else 'all'
                    np_ = exit_ts + 24 * 3600
                    if np_ > pause[key]: pause[key] = np_
        trades.append(t)
        open_pos.append((d, entry_ts, t))
    return trades, skipped

def s2_touched(d, bars, j0, k, lvl2):
    for b in bars[j0:k+1]:
        if d == 'long' and b['high'] >= lvl2: return True
        if d == 'short' and b['low'] <= lvl2: return True
    return False

def summarize(trades):
    closed = [t for t in trades if t['raw'] is not None]
    n = len(closed)
    if not n: return dict(n=0, total=0, wr=0, open=len(trades))
    wins = sum(1 for t in closed if t['raw'] > 0)
    tot = sum(t['sized'] for t in closed)
    eq = 0; peak = 0; mdd = 0
    for t in sorted(closed, key=lambda x: x['exit_ts']):
        eq += t['sized']; peak = max(peak, eq); mdd = min(mdd, eq - peak)
    return dict(n=n, total=round(tot, 1), wr=round(100*wins/n, 1), mdd=round(mdd, 1),
                open=len(trades)-n)

if __name__ == '__main__':
    bars = json.load(open('/tmp/bars_full.json'))
    # validation on live window: anchor = 2026-05-15 23:00 UTC (live anchor_ts)
    for code in 'ABC':
        tr, sk = run(bars, code, t_start=1778886000+1)
        s = summarize(tr)
        print(code, s, 'skipped:', sk)
