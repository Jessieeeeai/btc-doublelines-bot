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
    "📢 <b>[B] #024 / [C] #026 恢复为持仓中</b>, "
    "止损已锁定 <b>$65,688 (保底+1R)</b>, 继续等 8R 止盈或锁价出场。"
)

NOTICE_EN = (
    "📢 <b>[B] #024 / [C] #026 are restored as OPEN</b>, "
    "stops locked at <b>$65,688 (+1R secured)</b>, continuing toward the 8R target."
)

DISCORD_TEXT = (
    "📢 **[B] #024 / [C] #026 restored as OPEN**, stops locked at **$65,688 (+1R secured)**, "
    "continuing toward the 8R target.\n"
    "[B] #024 / [C] #026 恢复为持仓中, 止损已锁保底 +1R ($65,688), 继续等 8R。"
)

# 中文群兜底 (与 Secrets 里的 GROUP 合并去重)
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
    os.environ["TELEGRAM_GROUP_CHAT_ID"] = merged
    ok_cn = send_message(NOTICE_CN)
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
