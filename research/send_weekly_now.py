#!/usr/bin/env python3
"""一次性手动发一遍完整战绩汇总 (标题 + A/B/C 各一条 + 横向对比, 共5条) 到 TG。
发往 TELEGRAM_CHAT_ID + 可选 TELEGRAM_GROUP_CHAT_ID (私聊+群)。
不改 REPORT_FORMAT_VERSION、不触碰定时周报逻辑, 纯手动补发。
可在 Mac 本地跑 (自动读 .env), 也可由 GitHub Actions「手动周报」workflow 触发。"""
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

    api_key = os.environ.get("COINGLASS_API_KEY")
    if not api_key:
        sys.exit("缺少 COINGLASS_API_KEY")
    bars = m.fetch_btc_1h_bars(api_key, m.N_BARS)
    latest_btc = bars[-1]["close"]
    print(f"拉到 {len(bars)} 根, 最新 BTC ${latest_btc:,.0f}")

    strategies_data = [(s, m.load_state(s.state_file)) for s in m.STRATEGIES]
    m.send_summary_report(strategies_data, latest_btc, title="📊 战绩汇总 (手动补发)")
    print("战绩汇总已发送 (私聊 + 群)")


if __name__ == "__main__":
    main()
