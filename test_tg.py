"""
本地测试 TG 推送是否能通
用法:
  export TELEGRAM_BOT_TOKEN='你的token'
  export TELEGRAM_CHAT_ID='你的chat_id'
  python3 test_tg.py
"""
import os
import sys
from tg_notify import send_message

token = os.environ.get("TELEGRAM_BOT_TOKEN")
chat = os.environ.get("TELEGRAM_CHAT_ID")
if not token or not chat:
    print("ERROR: 请先 export TELEGRAM_BOT_TOKEN 和 TELEGRAM_CHAT_ID")
    sys.exit(1)

print(f"使用 Bot Token: {token[:10]}...{token[-4:]}")
print(f"发送到 chat_id: {chat}")

text = (
    "🤖 <b>F6 信号机器人测试</b>\n"
    "━━━━━━━━━━━━━━━\n"
    "如果你看到这条消息, 说明 Bot Token 和 chat id 配置成功!\n\n"
    "<i>可以接下来部署了 🚀</i>"
)
ok = send_message(text)
if ok:
    print("✅ 测试通过! 查看你 TG 应该收到了消息")
else:
    print("❌ 测试失败, 检查 token 和 chat_id 是否正确, 或者 Bot 是否被 chat 接受")
    print("提示: 必须先给你的 Bot 发过任何消息(/start 或随便发条), Bot 才能反向给你发消息")
