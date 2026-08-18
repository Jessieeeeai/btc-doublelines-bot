"""重叠颈线 · 关单图文战报: 平仓时生成复盘K线图 + caption, TG sendPhoto 推送。
风格对齐 F6 的 trade_report.py。matplotlib 不可用或出图失败自动降级纯文字。

图上标注 (英文防CJK字体缺失): 重叠区域框 / 颈线触发价 / entry / exit / SL路径(跟踪) / TP
"""
from datetime import datetime

from tg_notify import send_photo, send_message

GRAY = "#888780"
RED = "#E24B4A"
TEAL = "#1D9E75"
AMBER = "#BA7517"
BLUE = "#378ADD"
UP = "#1D9E75"
DOWN = "#E24B4A"
SL_RED = "#A32D2D"
ZONE = "#378ADD"


def _d(ts):
    return datetime.utcfromtimestamp(ts)


def _fmt_t(ts):
    return datetime.utcfromtimestamp(ts).strftime("%m-%d %H:%M")


def derive_sl_path(trade, bars, sl_mult=1.5):
    """从K线复算跟踪止损路径 (bot不存逐bar轨迹, 但轨迹由 bars+参数唯一决定)。
    返回 [(t0, t1, level), ...]。固定TP马 (tp非空) 只有一段初始SL。"""
    d = trade["direction"]
    level, L = trade["level"], trade["L"]
    entry_ts, exit_ts = trade["entry_ts"], trade["exit_ts"]
    init_sl = level - sl_mult * L if d == "long" else level + sl_mult * L
    if trade.get("tp"):  # 固定TP马: SL不动
        return [(entry_ts, exit_ts, init_sl)]
    segs = []
    sl = init_sl
    peak = trade["entry"]
    t0 = entry_ts
    dist = sl_mult * L
    for b in bars:
        if b["ts"] <= entry_ts or b["ts"] > exit_ts:
            continue
        fav = b["high"] if d == "long" else b["low"]
        peak = max(peak, fav) if d == "long" else min(peak, fav)
        new_sl = peak - dist if d == "long" else peak + dist
        better = new_sl > sl if d == "long" else new_sl < sl
        if better:
            segs.append((t0, b["ts"], sl))
            sl, t0 = new_sl, b["ts"]
    segs.append((t0, exit_ts, sl))
    return segs


def render_chart(code, trade, bars, sl_mult=1.5):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import matplotlib.patches as mpatches

    entry_ts, exit_ts = trade["entry_ts"], trade["exit_ts"]
    pad_l, pad_r = 24 * 3600, 8 * 3600
    win = [b for b in bars if entry_ts - pad_l <= b["ts"] <= exit_ts + pad_r]
    if len(win) < 5:
        raise ValueError(f"窗口内K线不足({len(win)})")

    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
    w = 1 / 24 * 0.65
    for b in win:
        x = mdates.date2num(_d(b["ts"]))
        up = b["close"] >= b["open"]
        c = UP if up else DOWN
        ax.vlines(x, b["low"], b["high"], color=c, linewidth=0.7, alpha=0.9)
        body = abs(b["close"] - b["open"]) or (b["high"] - b["low"]) * 0.01 + 0.01
        ax.bar(x, body, width=w, bottom=min(b["open"], b["close"]),
               color=c, alpha=0.9 if up else 0.85, linewidth=0)

    x0, x1 = _d(entry_ts), _d(exit_ts)
    d = trade["direction"]
    segs = derive_sl_path(trade, bars, sl_mult)

    # 重叠区域框 (形态本体, 画在入场前24h~入场)
    neck_lo, neck_hi = trade.get("neck_lo"), trade.get("neck_hi")
    if neck_lo and neck_hi:
        zx0 = mdates.date2num(_d(max(win[0]["ts"], entry_ts - 6 * 3600)))
        zx1 = mdates.date2num(_d(entry_ts + 2 * 3600))
        rect = mpatches.Rectangle((zx0, neck_lo), zx1 - zx0, neck_hi - neck_lo,
                                  linewidth=1.0, edgecolor=ZONE, facecolor=ZONE, alpha=0.15)
        ax.add_patch(rect)
        ax.annotate(f"zone {neck_lo:,.0f}~{neck_hi:,.0f}", (zx0, neck_hi), fontsize=7,
                    color=ZONE, ha="left", va="bottom")

    lo = min(min(b["low"] for b in win), *[s[2] for s in segs], trade["entry"], trade["exit"])
    hi = max(max(b["high"] for b in win), *[s[2] for s in segs], trade["entry"], trade["exit"])
    rng = hi - lo

    # TP (固定TP马)
    if trade.get("tp"):
        tp = trade["tp"]
        if lo - 0.35 * rng <= tp <= hi + 0.35 * rng:
            ax.hlines(tp, x0, x1, color=TEAL, linestyle="--", linewidth=1.3)
            ax.annotate(f"TP {tp:,.0f}", (x0, tp), fontsize=8, color=TEAL,
                        ha="left", va="bottom")
            lo, hi = min(lo, tp), max(hi, tp)
            rng = hi - lo
    # SL 路径 (跟踪马会呈阶梯)
    for t0s, t1s, lvl in segs:
        ax.hlines(lvl, _d(t0s), _d(t1s), color=SL_RED, linewidth=1.6)
    ax.annotate(f"SL0 {segs[0][2]:,.0f}", (x0, segs[0][2]), fontsize=8,
                color=SL_RED, ha="left", va="bottom")
    ax.set_ylim(lo - 0.07 * rng, hi + 0.07 * rng)

    short = d == "short"
    ax.plot([x0], [trade["entry"]], marker="v" if short else "^",
            color=BLUE, markersize=10, zorder=5)
    ax.annotate(f"entry {trade['entry']:,.0f}", (x0, trade["entry"]), fontsize=9,
                color=BLUE, ha="left", va="top" if short else "bottom",
                xytext=(6, -10 if short else 10), textcoords="offset points")
    exit_col = TEAL if trade["pnl_usd"] >= 0 else RED
    ax.plot([x1], [trade["exit"]], marker="o", color=exit_col, markersize=9, zorder=5)
    ax.annotate(f"exit {trade['exit']:,.0f}", (x1, trade["exit"]), fontsize=9,
                color=exit_col, ha="right", xytext=(-6, 10), textcoords="offset points")

    ax.set_title(f"[{code}] #{trade['seq']:03d} {'SHORT' if short else 'LONG'}  "
                 f"{trade['pnl_usd']:+,.0f} USD  (paper)", fontsize=11, loc="left")
    ax.yaxis.set_major_formatter(lambda v, _: f"${v:,.0f}")
    span_days = (win[-1]["ts"] - win[0]["ts"]) / 86400
    fmt = "%m-%d %H:%M" if span_days < 4 else "%m-%d"
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=7))
    ax.xaxis.set_major_formatter(mdates.DateFormatter(fmt))
    ax.tick_params(axis="x", labelsize=8)
    ax.grid(True, linewidth=0.3, alpha=0.4)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    fig.tight_layout()

    import io
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def build_caption(code, horse_name, trade, footer=""):
    short = trade["direction"] == "short"
    reason = {"TP": "🎯 打到TP目标价, 止盈出场",
              "SL": "🛑 打到止损出场",
              "TRAIL": "🔒 回踩打到跟踪止损, 锁利出场"}.get(trade["exit_reason"], trade["exit_reason"])
    lines = [
        f"🧾 <b>[{code}] #{trade['seq']:03d} 关单复盘</b> — {horse_name}",
        f"{'📉 空单' if short else '📈 多单'} · 名义 ${trade.get('notional', 10000):,.0f}",
        "━━━━━━━━━━━━━━━",
        f"📐 重叠区 {trade.get('neck_lo', 0):,.0f}~{trade.get('neck_hi', 0):,.0f} (L=${trade['L']:,.0f})",
        f"✅ {_fmt_t(trade['entry_ts'])} 进场 <code>${trade['entry']:,.0f}</code>",
        reason,
        f"🏁 {_fmt_t(trade['exit_ts'])} 出场 <code>${trade['exit']:,.0f}</code>",
        "━━━━━━━━━━━━━━━",
        f"💰 <b>{'+' if trade['pnl_usd'] >= 0 else '-'}${abs(trade['pnl_usd']):,.2f}</b>"
        f" · 持仓 {trade['bars_held']} 小时",
    ]
    text = "\n".join(lines)
    if footer:
        text += footer
    return text


def send_trade_report(code, horse_name, trade, bars, footer="", sl_mult=1.5):
    """平仓战报入口。出图失败自动降级纯文字, 永不抛异常。"""
    try:
        caption = build_caption(code, horse_name, trade, footer)
    except Exception as e:
        print(f"  [report] caption 失败: {e}")
        return
    try:
        png = render_chart(code, trade, bars, sl_mult)
        if send_photo(png, caption):
            return
    except Exception as e:
        print(f"  [report] 出图失败, 降级纯文字: {type(e).__name__}: {e}")
    send_message(caption)
