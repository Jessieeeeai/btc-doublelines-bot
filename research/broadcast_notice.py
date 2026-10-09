#!/usr/bin/env python3
"""全渠道广播一条通知: 中文TG(私聊+群) + 英文TG群 + Discord。
文案改 NOTICE_CN / NOTICE_EN / DISCORD_TEXT 即可复用。由「广播通知」workflow 触发。"""
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

NOTICE_CN = (
    "📢 <b>双线反转信号 (A/B/C 三条线) 暂停对外推送</b>\n\n"
    "自 7 月中旬以来策略连续亏损 (B/C 近三个月 28 笔无一盈利), 已超出历史回测的回撤范围。"
    "在原因查清、行情类型改变之前, 不再向群内推送开仓/平仓信号。\n\n"
    "机器人本身继续纸面记账, 之后会复盘这段停发期的数据, 恢复推送时另行通知。"
    "现有持仓请自行按止损处理。谢谢大家。"
)

NOTICE_EN = (
    "📢 <b>Double-Line Reversal signals (strategies A/B/C) are paused</b>\n\n"
    "The strategy has been in a losing streak since mid-July (B/C: 28 trades, 0 wins over ~3 months), "
    "beyond anything in the 3-year backtest. Until the cause is understood or the regime changes, "
    "no open/close signals will be posted here.\n\n"
    "The bot keeps paper-tracking in the background; we'll review that data before resuming. "
    "Please manage any open positions by their stops. Thank you."
)

DISCORD_TEXT = (
    "📢 **Double-Line Reversal signals (A/B/C) are paused.**\n"
    "Losing streak since mid-July (B/C: 28 trades, 0 wins) is beyond the 3-year backtest range. "
    "No signals will be posted until the cause is understood or the regime changes. "
    "Bot keeps paper-tracking; please manage open positions by their stops."
)

GROUP_CHAT_IDS = "-5515956430,-1003953373413"


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


def send_discord(text):
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        print("[Discord] 未配置 DISCORD_WEBHOOK_URL, 跳过")
        return False
    payload = json.dumps({"content": text}).encode()
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
        print("[Discord] 已发送")
        return True
    except Exception as e:
        print(f"[Discord] 失败: {type(e).__name__}: {e}")
        return False


def main():
    load_env()
    from tg_notify import send_message

    # 1) 中文 TG: 私聊 + 群 (多目标)
    existing = os.environ.get("TELEGRAM_GROUP_CHAT_ID", "").strip()
    merged = ",".join(dict.fromkeys(
        x.strip() for x in f"{existing},{GROUP_CHAT_IDS}".split(",") if x.strip()))
    private = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    # 显式传 chat_id, 绕过 PAUSE_PUBLIC 的"不发群"规则 (停发通知本身必须到群)
    ok_cn = send_message(NOTICE_CN, chat_id=",".join(x for x in [private, merged] if x))
    print(f"[中文TG] {'已发送' if ok_cn else '失败'} → 私聊+群({merged})")

    # 2) 英文 TG 群 (单独目标)
    en_chat = os.environ.get("TG_EN_CHAT_ID")
    if en_chat:
        ok_en = send_message(NOTICE_EN, chat_id=en_chat)
        print(f"[英文TG] {'已发送' if ok_en else '失败'} → {en_chat}")
    else:
        print("[英文TG] 未配置 TG_EN_CHAT_ID, 跳过")

    # 3) Discord
    send_discord(DISCORD_TEXT)


if __name__ == "__main__":
    main()
