#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""获取 chat_id：先在 Telegram 里给新 bot 发一条消息（/start 即可），再跑本脚本。
    python3 get_chat_id.py
找到后自动写入 tg_config.json。"""
import json
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_P = os.path.join(HERE, "tg_config.json")
cfg = json.load(open(CFG_P))
tok = cfg["bot_token"]

with urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/getUpdates", timeout=15) as r:
    data = json.loads(r.read().decode())

chats = {}
for u in data.get("result", []):
    msg = u.get("message") or u.get("edited_message") or {}
    ch = msg.get("chat", {})
    if ch.get("id"):
        chats[ch["id"]] = f"{ch.get('type')} | {ch.get('title') or ch.get('username') or ch.get('first_name')}"

if not chats:
    print("没找到消息。请先在 Telegram 里搜到你的新 bot，发送 /start，再重新运行本脚本。")
else:
    for cid, desc in chats.items():
        print(f"chat_id = {cid}  ({desc})")
    if len(chats) == 1:
        cid = str(list(chats)[0])
        cfg["chat_id"] = cid
        json.dump(cfg, open(CFG_P, "w"), ensure_ascii=False, indent=2)
        print(f"\n已自动写入 tg_config.json（chat_id={cid}）。现在运行: python3 tg.py test")
    else:
        print("\n检测到多个会话，请手动把想要的 chat_id 填入 tg_config.json。")
