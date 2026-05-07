# 🚂 Railway 部署指南 — Discord 抽獎機器人

---

## 📁 專案結構

```
deploy/
├── discord_lottery_bot.py   ← 機器人主程式
├── requirements.txt         ← Python 套件清單
├── railway.json             ← Railway 部署設定
├── Procfile                 ← 啟動指令
└── .gitignore
```

---

## 🔧 步驟一：Discord Developer Portal 設定

1. 前往 https://discord.com/developers/applications
2. 點 **New Application** → 命名 → 建立
3. 左側 **Bot** 頁面：
   - 點 **Reset Token** → **複製 Token**（等下要用）
   - 開啟以下 Intents：
     - ✅ SERVER MEMBERS INTENT
     - ✅ MESSAGE CONTENT INTENT
4. 左側 **OAuth2 → URL Generator**：
   - Scopes 勾選：`bot`、`applications.commands`
   - Bot Permissions 勾選：
     - Send Messages
     - Embed Links
     - Use Slash Commands
     - Mention Everyone
5. 複製產生的邀請連結 → 開啟 → 加入你的伺服器

---

## 🚂 步驟二：部署到 Railway

### 方法 A：用 GitHub 部署（推薦）

1. 在 GitHub 建一個新的 Repository
2. 把 `deploy/` 資料夾裡的所有檔案上傳到 repo 根目錄
3. 前往 https://railway.app → 登入（用 GitHub 帳號）
4. 點 **New Project → Deploy from GitHub Repo**
5. 選擇剛才建的 Repository
6. Railway 會自動偵測 Python 專案並開始部署

### 方法 B：用 Railway CLI 部署

```bash
# 安裝 Railway CLI
npm install -g @railway/cli

# 登入
railway login

# 在 deploy 資料夾中初始化
cd deploy
railway init

# 部署
railway up
```

---

## 🔑 步驟三：設定環境變數（最重要！）

在 Railway Dashboard 中：

1. 點進你的專案
2. 點選你的 Service
3. 進入 **Variables** 分頁
4. 點 **New Variable**，加入：

| Variable Name   | Value               |
|-----------------|---------------------|
| `DISCORD_TOKEN` | 你的 Bot Token      |

⚠️ **絕對不要把 Token 直接寫在程式碼裡或上傳到 GitHub！**

---

## ⚙️ 步驟四：確認部署設定

在 Railway Dashboard → 你的 Service → **Settings**：

- **Start Command** 應該顯示：`python discord_lottery_bot.py`
  （railway.json 已自動設定，通常不用手動改）
- **Restart Policy**：ON_FAILURE（自動重啟）

---

## ✅ 步驟五：確認上線

1. 在 Railway Dashboard 查看 **Deployments** 分頁
2. 點進最新的部署，查看 Logs
3. 應該會看到：
   ```
   🚀 正在啟動抽獎機器人...
   ✅ 機器人已上線：你的Bot名稱#1234
   📡 已加入 1 個伺服器
   ```
4. 到 Discord 伺服器輸入 `/抽獎面板` 測試

---

## 💡 注意事項

### 費用
- Railway 提供每月 $5 美元的免費額度（Trial Plan）
- Discord Bot 用量很低，通常免費額度就夠用
- 超過的話是按用量計費（約 $0.000231/min）

### 常見問題

**Q: 部署後 Bot 沒上線？**
→ 檢查 Variables 裡的 `DISCORD_TOKEN` 是否正確

**Q: 斜線指令沒出現？**
→ 等 1-2 分鐘讓 Discord 同步，或重新邀請 Bot 到伺服器

**Q: 部署失敗？**
→ 查看 Deploy Logs，通常是 requirements.txt 格式或 Python 版本問題

**Q: Bot 會自動重啟嗎？**
→ 會，railway.json 已設定 ON_FAILURE 重啟策略
