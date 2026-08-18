#!/usr/bin/env python3
"""一次性广播一条通知到所有信号接收方 (私聊 + 群, 走 tg_notify 多目标)。
可 Mac 本地跑 (读 .env), 也可由「广播通知」workflow 触发。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

NOTICE = (
    "📢 <b>通知</b>\n"
    "━━━━━━━━━━━━━━━\n"
    "不好意思，策略因为技术问题从 <b>7 月 12 日</b>起卡住了一段时间，"
    "期间暂停了开新单。\n\n"
    "现已排查修复、<b>正常重新启动</b>，信号推送恢复正常。\n"
    "给大家带来不便，非常抱歉！🙏"
)


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


# 所有群目标 (私聊从 .env 的 TELEGRAM_CHAT_ID 读; 群在这里显式指定)
GROUP_CHAT_IDS = "-5515956430,-1003953373413"


def main():
    load_env()
    # 确保发到两个群 (即使 .env 里没配 GROUP)
    existing = os.environ.get("TELEGRAM_GROUP_CHAT_ID", "").strip()
    merged = ",".join(x for x in [existing, GROUP_CHAT_IDS] if x)
    os.environ["TELEGRAM_GROUP_CHAT_ID"] = merged
    from tg_notify import send_message
    ok = send_message(NOTICE)
    if ok:
        print(f"广播已发送 → 私聊({os.environ.get('TELEGRAM_CHAT_ID')}) + 群({merged})")
    else:
        print("广播发送失败 (检查 .env 里的 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")


if __name__ == "__main__":
    main()
