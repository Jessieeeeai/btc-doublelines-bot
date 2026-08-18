# 大漂亮资金流秘籍 — GitHub Actions 部署指南

流程与 F6 机器人完全一致，5 分钟搞定。

## 第 1 步：创建私有仓库

GitHub 右上角 `+` → `New repository` → 名字随意（如 `dpl-flow-bot`）→
**务必选 Private** → Create。

## 第 2 步：推送代码

```bash
cd ~/Desktop/交易/gojibot/deploy
git init && git branch -M main
git add .
git commit -m "deploy 大漂亮资金流秘籍"
git remote add origin https://github.com/你的用户名/dpl-flow-bot.git
git push -u origin main
```

## 第 3 步：配置 Secrets

仓库页面 → Settings → Secrets and variables → Actions → New repository secret，
添加三个（和 F6 仓库里的一样）：

| Name | 内容 |
|------|------|
| `COINGLASS_API_KEY` | CoinGlass API key |
| `TELEGRAM_BOT_TOKEN` | `8989717973:AAF...`（新bot的token） |
| `TELEGRAM_CHAT_ID` | `6070865545` |

## 第 4 步：启用并测试

仓库 → Actions 标签 → 启用 workflows → 选「大漂亮资金流秘籍信号机器人」→
`Run workflow` 手动跑一次 → 看 logs 确认输出 `BTC bar=... state 已保存`。

之后每小时第 7 分钟自动运行，**Mac 关机也照跑**。

## 播报内容

- 🔔 开单：文字卡（品种/方向/触发条件/入场/L01止损/1.5R止盈/C层杠杆）
- 🧾 关单：**K线复盘图**（蜡烛+TP虚线+SL红线+entry/exit标记，F6同款）+
  时间线 caption + 累计战绩 + vs 回测预期
- 出图失败自动降级纯文字，不丢消息

## 与本地 launchd 版的关系

GitHub 版上线后，本地版建议卸载避免重复推送：

```bash
launchctl unload ~/Library/LaunchAgents/com.gojibot.monitor.plist
```

（本地 forward/ 里已积累的记录保留不动。）

## 策略与红线

跟踪 S10·阻力衰竭做空（BTC）+ S20·恐慌衰竭做多（BTC/ETH），纸面验证模式。
实盘授权条件见《大漂亮资金流秘籍·交易体系手册 v2.0》第八节。
