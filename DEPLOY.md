# 球星卡价值分析系统 — 部署与运维指南

> 正式投入使用的手册：常驻服务、自动数据更新、手机访问、桌面 App 化、云服务器部署。

## 一、总体架构

```
┌─────────────────────────────────────────────────────┐
│  运行电脑（本机或云服务器）                            │
│                                                     │
│  ┌──────────┐   ┌──────────┐   ┌────────────────┐  │
│  │ Streamlit│   │  FastAPI │   │ 定时任务        │  │
│  │ 界面 :8501│   │ API :8000│   │ 每天 03:00      │  │
│  └────┬─────┘   └────┬─────┘   │ update_all     │  │
│       │              │         └───────┬────────┘  │
│       └──────┬───────┘                 │           │
│        模型 + 数据（本地文件）          │           │
│        models/*.joblib  ◄──────────────┘ 采集→重训 │
│        data/*.csv                       │           │
│  ┌──────────────────────────────────────┘           │
│  │ 采集: eBay (Playwright) + 卡淘 (requests)         │
│  └──────────────────────────────────────────────────┘
│  手机/平板: 局域网浏览器访问 http://<电脑IP>:8501      │
└─────────────────────────────────────────────────────┘
```

## 二、本机部署

### 2.1 首次部署

```powershell
cd <项目根目录>          # 例如 C:\star-card-analyzer

# 1. 激活环境（如被拦截先执行: Set-ExecutionPolicy -Scope Process Bypass）
venv\Scripts\Activate.ps1
chcp 65001
$env:PYTHONIOENCODING = "utf-8"

# 2. 安装依赖（若 venv 未创建，先跑 scripts\install.bat）
pip install -r requirements.txt
playwright install chromium

# 3. 采集真实数据 + 训练模型（首次约 30-60 分钟；不采集可用内置预训练模型）
python scripts\build_comps_db.py --players 15 --cardhobby-pages 30
python train.py

# 4. 启动界面（会保持运行）
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

启动后浏览器打开 **http://localhost:8501** 即可使用。

### 2.2 日常使用

- **双击** `scripts\start_app.bat` → 自动启动界面（本机 http://localhost:8501，同网段手机 http://<电脑IP>:8501）
- 关闭服务：在批处理窗口按 `Ctrl+C`

### 2.3 开机自启（Windows 可选）

把 `start_app.bat` 的快捷方式放入：`Win+R` → `shell:startup` → 粘贴快捷方式。
以后开机自动启动系统。

## 三、数据自动更新（让模型持续学习最新市场）

### 3.1 更新策略

> **eBay 更新慢（30-60 分钟）且易触发限流 → 不建议每天自动跑。**
> 每日任务只更新卡淘（快，3-10 分钟）；eBay 按需手动更新。

| 内容 | 方式 | 耗时 |
|------|------|------|
| 卡淘每日更新 + 模型重训 | 定时任务每天 03:00 自动 | 3-10 分钟 |
| eBay 数据更新 | **手动**运行 `update_ebay_manual.bat` | 30-60 分钟 |
| 两者一起完整更新 | `python scripts\update_all.py` | 30-60 分钟 |

### 3.2 注册 Windows 定时任务（每天自动更新卡淘）

PowerShell **以管理员身份**运行（任务计划要求绝对路径）：

```powershell
schtasks /Create /TN "StarCard_Update" /TR "<项目根目录>\scripts\update_all.bat" /SC DAILY /ST 03:00
```

- 每天凌晨 03:00 自动更新卡淘数据 + 重训模型（**不包含 eBay**）
- 日志：`logs\update_YYYYMMDD_HHMMSS.log`（自动保留 30 天）
- 查看任务：`schtasks /Query /TN "StarCard_Update"`
- 立即跑一次测试：`schtasks /Run /TN "StarCard_Update"`
- 删除任务：`schtasks /Delete /TN "StarCard_Update" /F`

> ⚠️ 注意：定时任务运行时电脑必须开机。笔记本可设置"电源选项 → 不睡眠"，
> 或追加开机触发任务：`schtasks /Create /TN "StarCard_Update_OnBoot" /TR "<项目根目录>\scripts\update_all.bat" /SC ONLOGON`

### 3.3 手动更新 eBay（自选）

**双击 `scripts\update_ebay_manual.bat`**，或命令行：

```powershell
# 仅 eBay（15 名球星 × 7 系列 × 2 页）+ 重训
python scripts\update_all.py --ebay-only --players 15 --ebay-pages 2

# 自定义规模（更快）：只采前 5 名球星 1 页，约 10-15 分钟
python scripts\update_all.py --ebay-only --players 5 --ebay-pages 1
```

- 启动时会**醒目标注预计耗时**（30-60 分钟），期间请勿关闭窗口、保持电脑不睡眠
- 建议在晚间/闲时运行（白天 eBay 限流概率更高）
- 支持中途 Ctrl+C 中断：已采集数据会缓存，重跑不丢
- 频繁被 403 限流时加大间隔：`--search-delay 10`，或分两次跑

## 四、手机 / 平板访问

1. 电脑和手机连同一个 WiFi
2. 电脑查 IP：`ipconfig` → IPv4 地址（如 192.168.1.5）
3. 手机浏览器打开 `http://192.168.1.5:8501`（防火墙需放行 8501 端口）

Streamlit 自带移动端适配。iPhone Safari / Android Chrome 可"添加到主屏幕"获得伪 App 体验。

### 公网访问（随时随地在外面用）

| 方案 | 优点 | 缺点 | 适合 |
|------|------|------|------|
| 内网穿透（推荐）: [frp](https://github.com/fatedier/frp) / [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) | 免费、无需服务器 | 需要配置 | 个人自用 |
| 云服务器 + 反向代理 | 稳定、可备案域名 | 花钱（~¥100/年） | 长期/多用户 |

Cloudflare Tunnel 最省事（免费、免公网 IP、自带 HTTPS）：
```powershell
# 电脑安装 cloudflared 后一行启动（需先注册 Cloudflare 账号）
cloudflared tunnel --url http://localhost:8501
```
会输出一个 `https://xxx.trycloudflare.com` 地址，手机在任何网络都能访问。

## 五、桌面 App 化（Windows 应用双击即用）

### 方案 A：Tauri 壳（推荐，轻量 ~5MB）

1. 安装 Rust 工具链（https://rustup.rs）
2. 新建壳工程，main.rs 里 `Command::new("streamlit").args(["run", "app.py"]).spawn()` 并打开默认浏览器
3. `tauri build` 得到安装包，双击即用，自动拉起服务和浏览器

### 方案 B：Electron 壳（开发快但 ~150MB）

用 electron 包一层，main.js 启动 streamlit 子进程 + BrowserWindow 内嵌页面。
配合 [electron-builder](https://www.electron.build/) 打包成 exe。

### 方案 C：脚本 + 快捷方式（零成本，够用）

`start_app.bat` 已经实现：双击 → 启动服务 + 自动打开浏览器。
建一个桌面快捷方式 + 自定义图标即可。

> 建议：个人使用选 **方案 C**（现成），要分享给朋友用再上 **方案 A (Tauri)**。

## 六、原生手机 App（远期方案）

Streamlit 界面无法直接打包成原生 App，需要重写前端：

```
原生 App (Flutter/React Native)  ──HTTP──►  FastAPI 后端 (src/api/main.py)
                                                  │
                                          模型 + 数据（同一套）
```

### API 端点清单（当前）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查（模型是否就绪） |
| POST | `/evaluate` | 卡片估价（18 字段，见 CardRequest） |
| POST | `/api/agent/chat` | AI 助手对话（OpenAI 兼容消息格式，带工具调用；未配置 LLM Key 时降级返回） |

`/api/agent/chat` 请求体：`{messages: [{role, content}, ...], session_id: "可选，留空自动生成"}`
（只取最后一条 user 消息追加进服务端会话，防伪造历史；会话存内存，上限 200 个，重启即失）。
响应：`{reply, tool_calls, session_id, degraded}`。
LLM 走 `agent.env` 或环境变量配置：`OPENAI_API_KEY`（必填）、`OPENAI_BASE_URL`（默认 DeepSeek）、`AGENT_MODEL`。

## 七、云服务器部署（长期 / 多人使用）

> ⚠️ 关键约束：**卡淘（.com.cn）国内网络可访问；eBay 反爬对国内 IP 严格**。
> 若部署在境外服务器，卡淘连接可能超时；若在国内服务器，eBay 采集受限。
> 结论：**个人自用以"本机部署 + 内网穿透"为主**，云服务器仅当需要 7x24 在线时考虑。

国内服务器方案（阿里云/腾讯云轻量，Ubuntu）：

```bash
# 1. 上传代码，安装依赖
cd /opt/star-card-analyzer
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install chromium --with-deps

# 2. 采集 + 训练（可选，有预训练模型可跳过）
python scripts/build_comps_db.py --players 15 --cardhobby-pages 30
python train.py

# 3. 常驻服务（systemd）
cat > /etc/systemd/system/starcard.service <<'EOF'
[Unit]
Description=Star Card Analyzer
After=network.target

[Service]
WorkingDirectory=/opt/star-card-analyzer
ExecStart=/opt/star-card-analyzer/venv/bin/streamlit run app.py --server.address 0.0.0.0 --server.port 8501
Restart=always

[Install]
WantedBy=multi-user.target
EOF
systemctl enable --now starcard

# 4. 定时更新（crontab，每天 03:00）
crontab -e
# 添加一行:
0 3 * * * cd /opt/star-card-analyzer && ./venv/bin/python scripts/update_all.py >> logs/cron.log 2>&1
```

安全：云服务器记得配置安全组放行 8501 端口（或套 Nginx + HTTPS 域名）。

## 八、运维速查

| 操作 | 命令 |
|------|------|
| 启动界面 | 双击 `scripts\start_app.bat` 或 `streamlit run app.py` |
| 启动 API | `uvicorn src.api.main:app --host 0.0.0.0 --port 8000` |
| 启用 AI 助手 | 编辑 `agent.env` 填入 OPENAI_API_KEY 后重启（详见 README） |
| 手动更新数据+模型 | `python scripts\update_all.py` |
| 仅采集数据 | `python scripts\build_comps_db.py --players 15 --cardhobby-pages 30` |
| 仅重训模型 | `python train.py` |
| eBay 登录（解锁已售出） | `python scripts\build_comps_db.py --ebay-login` |
| 查看更新日志 | 看最新 `logs\update_*.log` |
| 查看定时任务 | `schtasks /Query /TN "StarCard_Update"` |
| 备份 | 复制 `data\*.csv`、`models\*.joblib`、`logs\` 三处即可 |

## 九、故障排查

| 症状 | 原因 | 处理 |
|------|------|------|
| 界面打开但估价空白 | 模型未训练 | `python train.py` |
| eBay 采到 0 条 | IP 限流（冷却期） | 等 30-60 分钟重跑；`--search-delay 10` |
| 卡淘采到 0 条 | 深夜无出价商品 | 白天/晚间重跑；加大 `--cardhobby-pages 60` |
| 定时任务不执行 | 电脑关机/睡眠 | 见 3.2 开机补跑；或检查 `schtasks /Query` |
| 手机打不开 | 防火墙拦截 | 放行 8501: `netsh advfirewall firewall add rule name="starcard" dir=in action=allow protocol=TCP localport=8501` |
| Playwright 报错缺浏览器 | 未安装浏览器内核 | `playwright install chromium` |
