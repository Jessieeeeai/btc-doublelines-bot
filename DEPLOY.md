# F6 信号机器人 — GitHub Actions 部署指南

## 部署流程（首次约 15 分钟）

### 第 1 步：注册 GitHub 账户（已有跳过）

去 [github.com](https://github.com) 注册账户，验证邮箱。

### 第 2 步：创建私有仓库

1. 登录 GitHub，右上角点 `+` → `New repository`
2. Repository name: `btc-signal-bot`（随便起）
3. **务必选 `Private`**（不要选 Public，state.json 里会有交易历史）
4. 不勾选 "Add a README" 之类
5. 点 `Create repository`

### 第 3 步：把代码推送到仓库

在你 Mac 终端里：

```bash
cd "/Users/guoxiaoquandediannao/Desktop/交易"

# 初始化 git (如果还没初始化)
git init
git branch -M main

# .gitignore 已经存在,会自动排除 .env / data/ / results/

# 提交代码
git add .
git commit -m "initial deploy F6 signal bot"

# 连接到你刚创建的 GitHub 仓库 (把 USERNAME 换成你的 GitHub 用户名)
git remote add origin https://github.com/USERNAME/btc-signal-bot.git
git push -u origin main
```

第一次 push 可能让你登录 GitHub。如果用 https 失败，建议用 GitHub Desktop App 推送（最省事）。

### 第 4 步：配置 Secrets（让 GitHub 知道你的 API key 和 TG Token）

1. 在你的 GitHub 仓库页面，点 `Settings`（页面上方右侧）
2. 左侧菜单点 `Secrets and variables` → `Actions`
3. 点 `New repository secret`，添加三个：

| Name | Secret 内容 |
|------|------------|
| `COINGLASS_API_KEY` | 你的 Coinglass API key |
| `TELEGRAM_BOT_TOKEN` | 你从 BotFather 拿到的 Token |
| `TELEGRAM_CHAT_ID` | 你的 chat_id（纯数字）|

**每个都要点 `Add secret` 保存**。

### 第 5 步：启用 Workflow

1. 在仓库页面点 `Actions` 标签
2. 第一次访问可能会提示 "Workflows aren't being run on this forked repository" — 点 "I understand my workflows, go ahead and enable them"
3. 左侧应该能看到 "F6 信号机器人" workflow
4. 点击它，然后点右侧 `Run workflow` 手动跑一次确认能成功

### 第 6 步：开心收信号 🎉

之后每 5 分钟自动跑一次。你 Mac 关机也没事。

---

## 怎么看运行状态

- **看历史**：`Actions` 标签 → 点任意一次运行 → 看 logs
- **看当前 state**：仓库里的 `state.json` 文件，会随每次有新信号/状态变化更新
- **TG 收消息**：信号形成/入场/出场都会推

---

## 撤销/换 Token

如果 Token 泄漏需要换：

1. Telegram 里找 BotFather
2. 发 `/revoke` → 选你的 Bot → 拿到新 Token
3. GitHub 仓库 → Settings → Secrets → 找到 `TELEGRAM_BOT_TOKEN` → Update 成新的

---

## 月底战报

机器人会自动判定：当 10 个信号全部走到终态（TP/SL/作废）时，发一条战报到 TG。

如果你想中途看进度，可以：
- 看仓库的 `state.json`（每个信号的状态都在里面）
- 或在 Actions 里手动 `Run workflow` 一次，看日志输出
