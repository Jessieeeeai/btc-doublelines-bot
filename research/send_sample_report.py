#!/usr/bin/env python3
"""发样例关单战报到 TG: C#005 (带加仓+双锁, +11.5R) 和 B#008 (止损, -1R)。
可在 Mac 本地跑 (自动读 .env), 也可由 GitHub Actions 的「样例战报」workflow 触发。"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)


def load_env():
    path = os.path.join(REPO, ".env")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main():
    load_env()
    import signal_bot_race as m
    from trade_report import send_trade_report
    from tg_notify import send_message

    api_key = os.environ.get("COINGLASS_API_KEY")
    if not api_key:
        sys.exit("缺少 COINGLASS_API_KEY")
    bars = m.fetch_btc_1h_bars(api_key, 990)
    print(f"拉到 {len(bars)} 根 K 线")

    send_message("🧪 <b>关单战报样例</b> — 下面两条是历史单的复盘演示")
    for code, idx in (("C", 5), ("B", 8)):
        strategy = [s for s in m.STRATEGIES if s.code == code][0]
        state = m.load_state(os.path.join(REPO, os.path.basename(strategy.state_file)))
        sig = state["signals"][idx - 1]
        send_trade_report(strategy.code, strategy.name, idx, sig, bars,
                          dollar_pl=m.signal_dollar_pl(sig) or 0,
                          footer=m.fmt_stats_footer(strategy, state))
        print(f"[{code}] #{idx:03d} 样例已发")


if __name__ == "__main__":
    main()
