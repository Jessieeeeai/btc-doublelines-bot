"""关单图文战报: 每笔单平仓时, 生成该笔交易的复盘 K 线图 + 时间线 caption,
经 TG sendPhoto 推送。matplotlib 不可用或出图失败时自动降级为纯文字。

图上标注 (英文, 避免 CJK 字体缺失): entry / exit / TP / SL 路径 / +2R +4R 锁 / 加仓点
中文细节全部放 caption。
"""
from datetime import datetime

from tg_notify import send_photo, send_message

GRAY = "#888780"
RED = "#E24B4A"
TEAL = "#1D9E75"
AMBER = "#BA7517"
BLUE = "#378ADD"


def _d(ts):
    return datetime.utcfromtimestamp(ts)


def _fmt_t(ts):
    return datetime.utcfromtimestamp(ts).strftime("%m-%d %H:%M")


def derive_events(sig, bars):
    """从 K 线倒推锁/加仓的触发时间 (state 里只有 bool 没有时间戳)。
    只认 sig 里实际置位的 flag, K 线只用来定位时间。"""
    ev = {}
    entry = sig.get("entry_price")
    entry_ts = sig.get("entry_ts")
    r = sig.get("r_dollar") or 0
    exit_ts = sig.get("exit_ts") or float("inf")
    if not entry or not entry_ts or not r:
        return ev
    short = sig["direction"] == "short"
    for bar in bars:
        if bar["ts"] <= entry_ts or bar["ts"] > exit_ts:
            continue
        if sig.get("stair_2r_locked") and "lock2r" not in ev and \
                (bar["low"] <= entry - 2 * r if short else bar["high"] >= entry + 2 * r):
            ev["lock2r"] = bar
        if sig.get("stair_4r_locked") and "lock4r" not in ev and \
                (bar["low"] <= entry - 4 * r if short else bar["high"] >= entry + 4 * r):
            ev["lock4r"] = bar
        if sig.get("pyramid_entered") and "pyr" not in ev and \
                (bar["low"] <= entry - r if short else bar["high"] >= entry + r):
            ev["pyr"] = bar
    return ev


def _sl_path(sig, ev):
    """返回 [(t0, t1, level), ...] 的 SL 阶梯路径"""
    entry, r = sig["entry_price"], sig["r_dollar"]
    short = sig["direction"] == "short"
    t_entry = sig["entry_ts"]
    t_exit = sig.get("exit_ts")
    lock1 = entry - r if short else entry + r
    lock2 = entry - 2 * r if short else entry + 2 * r
    segs, t = [], t_entry
    if "lock2r" in ev:
        segs.append((t, ev["lock2r"]["ts"], sig["sl0"]))
        t = ev["lock2r"]["ts"]
        if "lock4r" in ev:
            segs.append((t, ev["lock4r"]["ts"], lock1))
            t = ev["lock4r"]["ts"]
            segs.append((t, t_exit, lock2))
        else:
            segs.append((t, t_exit, lock1))
    else:
        segs.append((t, t_exit, sig["sl0"]))
    return segs


def render_chart(code, sig_no, sig, bars, dollar_pl):
    """返回 PNG bytes。任何异常往上抛, 由调用方降级。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    entry_ts, exit_ts = sig["entry_ts"], sig["exit_ts"]
    pad_l, pad_r = 24 * 3600, 12 * 3600
    win = [b for b in bars if entry_ts - pad_l <= b["ts"] <= exit_ts + pad_r]
    if len(win) < 5:
        raise ValueError(f"窗口内 K 线不足 ({len(win)})")
    ev = derive_events(sig, bars)

    xs = [_d(b["ts"]) for b in win]
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
    ax.fill_between(xs, [b["low"] for b in win], [b["high"] for b in win],
                    color=GRAY, alpha=0.18, linewidth=0)
    ax.plot(xs, [b["close"] for b in win], color="#5F5E5A", linewidth=1.2)

    x0, x1 = _d(entry_ts), _d(exit_ts)
    segs = _sl_path(sig, ev)
    lo = min(min(b["low"] for b in win), sig["sl0"], sig["entry_price"],
             sig["exit_price"], *[s[2] for s in segs])
    hi = max(max(b["high"] for b in win), sig["sl0"], sig["entry_price"],
             sig["exit_price"], *[s[2] for s in segs])
    rng = hi - lo
    # TP 离价格太远 (比如 -1R 止损的 8R 单) 就不画线, 避免把走势压扁
    tp_in = lo - 0.35 * rng <= sig["tp"] <= hi + 0.35 * rng
    if tp_in:
        ax.hlines(sig["tp"], x0, x1, color=TEAL, linestyle="--", linewidth=1.3)
        ax.annotate(f"TP {sig['tp']:,.0f}", (x0, sig["tp"]), fontsize=8,
                    color=TEAL, ha="left", va="bottom")
        lo, hi = min(lo, sig["tp"]), max(hi, sig["tp"])
        rng = hi - lo
    else:
        edge = hi if sig["tp"] > hi else lo
        ax.annotate(f"TP {sig['tp']:,.0f} (off-chart)", (x0, edge), fontsize=8,
                    color=TEAL, ha="left",
                    va="top" if sig["tp"] < lo else "bottom")
    for t0, t1, lvl in segs:
        ax.hlines(lvl, _d(t0), _d(t1), color=RED, linewidth=1.6)
    ax.annotate(f"SL0 {sig['sl0']:,.0f}", (x0, sig["sl0"]), fontsize=8,
                color=RED, ha="left", va="bottom")
    ax.set_ylim(lo - 0.07 * rng, hi + 0.07 * rng)

    short = sig["direction"] == "short"
    ax.plot([x0], [sig["entry_price"]], marker="v" if short else "^",
            color=BLUE, markersize=10, zorder=5)
    ax.annotate(f"entry {sig['entry_price']:,.0f}", (x0, sig["entry_price"]),
                fontsize=9, color=BLUE, ha="left", va="top" if short else "bottom",
                xytext=(6, -10 if short else 10), textcoords="offset points")
    exit_col = TEAL if (sig.get("result_r") or 0) >= 0 else RED
    ax.plot([x1], [sig["exit_price"]], marker="o", color=exit_col,
            markersize=9, zorder=5)
    ax.annotate(f"exit {sig['exit_price']:,.0f}", (x1, sig["exit_price"]),
                fontsize=9, color=exit_col, ha="right",
                xytext=(-6, 10), textcoords="offset points")

    for key, label in (("lock2r", "+2R lock"), ("lock4r", "+4R lock")):
        if key in ev:
            bx = _d(ev[key]["ts"])
            ax.axvline(bx, color=AMBER, linewidth=0.8, alpha=0.6)
            ax.annotate(label, (bx, ax.get_ylim()[1]), fontsize=8, color=AMBER,
                        ha="left", va="top", xytext=(3, -2), textcoords="offset points")
    if "pyr" in ev:
        pyr_p = sig.get("pyramid_entry_price") or 0
        ax.plot([_d(ev["pyr"]["ts"])], [pyr_p], marker="D", color=AMBER,
                markersize=8, zorder=5)
        ax.annotate(f"add 0.5x {pyr_p:,.0f}", (_d(ev["pyr"]["ts"]), pyr_p),
                    fontsize=8, color=AMBER, ha="left", va="bottom",
                    xytext=(6, 6), textcoords="offset points")

    rr = sig.get("result_r") or 0
    ax.set_title(f"[{code}] #{sig_no:03d} {'SHORT' if short else 'LONG'}  "
                 f"{dollar_pl:+,.0f} USD ({rr:+.1f}R)", fontsize=11, loc="left")
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


def build_caption(code, strategy_name, sig_no, sig, bars, dollar_pl, footer=""):
    ev = derive_events(sig, bars)
    short = sig["direction"] == "short"
    entry, r = sig["entry_price"], sig["r_dollar"]
    rr = sig.get("result_r") or 0
    hold_h = (sig["exit_ts"] - sig["entry_ts"]) / 3600

    real_tp = sig["status"] == "tp_hit" and abs((sig.get("exit_price") or 0) - sig["tp"]) < 1
    if sig["status"] == "sl_hit":
        how = "🛑 打到止损出场"
    elif real_tp:
        how = "🎯 打到 TP 目标价, 止盈出场"
    else:
        how = "🔒 价格回踩打到锁价 SL, 锁住利润出场"

    lines = [
        f"🧾 <b>[{code}] #{sig_no:03d} 关单复盘</b> — {strategy_name}",
        f"{'📉 空单' if short else '📈 多单'} · 仓位 {sig.get('size_multiplier', 1.0):.2f}×",
        "━━━━━━━━━━━━━━━",
        f"🔔 {_fmt_t(sig['signal_ts'])} 信号形成",
        f"✅ {_fmt_t(sig['entry_ts'])} 进场 <code>${entry:,.0f}</code>"
        f" (SL ${sig['sl0']:,.0f} / TP ${sig['tp']:,.0f})",
    ]
    lock1 = entry - r if short else entry + r
    lock2 = entry - 2 * r if short else entry + 2 * r
    mid = []
    if "lock2r" in ev:
        mid.append((ev["lock2r"]["ts"],
                    f"🪜 {_fmt_t(ev['lock2r']['ts'])} 浮盈+2R, SL 锁到 ${lock1:,.0f}"))
    if "pyr" in ev:
        mid.append((ev["pyr"]["ts"],
                    f"🔺 {_fmt_t(ev['pyr']['ts'])} +1R 加仓 0.5× "
                    f"<code>${sig.get('pyramid_entry_price') or 0:,.0f}</code>"))
    if "lock4r" in ev:
        mid.append((ev["lock4r"]["ts"],
                    f"🪜 {_fmt_t(ev['lock4r']['ts'])} 浮盈+4R, SL 锁到 ${lock2:,.0f}"))
    lines.extend(t[1] for t in sorted(mid))
    lines.append(f"{how}")
    lines.append(f"🏁 {_fmt_t(sig['exit_ts'])} 出场 <code>${sig['exit_price']:,.0f}</code>")
    lines.append("━━━━━━━━━━━━━━━")
    money = ("+" if dollar_pl >= 0 else "-") + f"${abs(dollar_pl):,.2f}"
    lines.append(f"💰 <b>{money}</b> ({rr:+.1f}R) · 持仓 {hold_h:.0f} 小时")
    text = "\n".join(lines)
    if footer:
        text += footer
    return text


def send_trade_report(code, strategy_name, sig_no, sig, bars, dollar_pl, footer=""):
    """平仓战报入口。出图失败自动降级为纯文字, 永不抛异常。"""
    try:
        caption = build_caption(code, strategy_name, sig_no, sig, bars, dollar_pl, footer)
    except Exception as e:
        print(f"  [report] caption 失败: {e}")
        return
    try:
        png = render_chart(code, sig_no, sig, bars, dollar_pl)
        if send_photo(png, caption):
            return
    except Exception as e:
        print(f"  [report] 出图失败, 降级纯文字: {type(e).__name__}: {e}")
    send_message(caption)
