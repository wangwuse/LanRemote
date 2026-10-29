# LanRemote · 局域网遥控面板

> **躺在沙发上，用手机指挥电脑。**

LanRemote 是一个**轻量局域网遥控面板**：只发指令，不传画面。

它不是远程桌面，不传屏幕画面、不做视频流、不做远程终端 shell。
它是 TeamViewer / RustDesk 的反面——你不需要看到电脑屏幕，只需要按一个按钮让它
关个机、调个音量、发个 `Win+D`。

```
  手机（同一 WiFi）                    电脑
 ┌──────────────┐                 ┌──────────────┐
 │  🔊 音量+     │ ── 一条指令 ──▶ │ 执行系统动作  │
 │  ⏯ 播放/暂停  │                 │ 写一行操作日志│
 │  ⏻  关机      │ ◀── 结果反馈 ── │ 不回传任何画面│
 └──────────────┘                 └──────────────┘
        📱                                🖥️
```

---

## 安装

1. 解压 `LanRemote.zip` 到任意目录。
2. 双击启动：
   - **Windows**：双击 `start.bat`
   - **macOS / Linux**：`chmod +x start.sh && ./start.sh`

启动后终端会打印：

```
========================================================
  LanRemote v0.1  躺在沙发上，用手机指挥电脑
========================================================
  本机地址 : http://192.168.1.23:8765
  配对 PIN  : 482913
  平台      : Windows (10)
--------------------------------------------------------
  ██████████████  （ASCII 二维码，手机可扫）
--------------------------------------------------------
  手机与电脑连同一 WiFi，扫码或浏览器打开上面地址，
  首次连接输入 6 位 PIN。Ctrl+C 退出。
  仅限可信局域网使用，不要暴露到公网。
========================================================
```

**不需要** `pip install`，**不需要** node，**不需要**联网下载任何东西。
只要求本机有 **Python 3.8+**（Windows 装 Python 时记得勾选 "Add Python to PATH"）。

> 首次启动如果 `config.json` 里的 PIN 不是 6 位数字，程序会自动生成一个随机 PIN
> 并写回 `config.json`，所以你每次重装拿到的是新 PIN。想固定 PIN 就直接改
> `config.json` 里的 `"pin": "123456"`。

---

## 使用

1. 手机和电脑连**同一个 WiFi**（同一局域网网段）。
2. 手机浏览器打开终端显示的地址，或直接扫终端里的二维码。
3. 首次连接输入终端上显示的 **6 位 PIN**。
4. 配对成功后手机会被记住（12 小时内免 PIN），之后直接进面板。
5. 点按钮即可遥控。危险操作（关机 / 重启）会弹二次确认。

顶栏的圆点表示连接状态：绿色=已连接，黄色=连接中，红色=断开（会自动重连）。

---

## 支持的动作

| 分类 | 动作 | 指令 | Windows | macOS | Linux |
|---|---|---|---|---|---|
| 电源 | 关机 | `power_shutdown` | ✅ 已验证 | ⚠️ 待验证 | ⚠️ 待验证 |
| 电源 | 重启 | `power_reboot` | ✅ 已验证 | ⚠️ 待验证 | ⚠️ 待验证 |
| 电源 | 锁屏 | `power_lock` | ✅ 已验证 | ⚠️ 待验证 | ⚠️ 待验证 |
| 电源 | 休眠 | `power_sleep` | ✅ 已验证 | ⚠️ 待验证 | ⚠️ 待验证 |
| 媒体 | 音量 + | `media_volume_up` | ✅ 已验证 | ⚠️ 待验证 | ⚠️ 待验证 |
| 媒体 | 音量 − | `media_volume_down` | ✅ 已验证 | ⚠️ 待验证 | ⚠️ 待验证 |
| 媒体 | 静音切换 | `media_mute` | ✅ 已验证 | ⚠️ 待验证 | ⚠️ 待验证 |
| 媒体 | 播放 / 暂停 | `media_play_pause` | ✅ 已验证 | ⚠️ 待验证 | ⚠️ 待验证 |
| 媒体 | 上一首 | `media_prev` | ✅ 已验证 | ⚠️ 待验证 | ⚠️ 待验证 |
| 媒体 | 下一首 | `media_next` | ✅ 已验证 | ⚠️ 待验证 | ⚠️ 待验证 |
| 快捷键 | 6 个自定义组合键 | `shortcut_send` | ✅ 已验证 | ⚠️ 待验证 | ⚠️ 待验证 |

快捷键按钮在 `config.json` 的 `shortcut_buttons` 里配置，默认：

| 按钮 | 组合键 |
|---|---|
| 显示桌面 | `win+d` |
| 切换窗口 | `alt+tab` |
| 复制 | `ctrl+c` |
| 关闭程序 | `alt+f4` |
| 任务管理器 | `ctrl+shift+esc` |
| 运行 | `win+r` |

组合键写法：修饰键 + 一个普通键，用 `+` 连接。
修饰键可用 `win` / `cmd` / `ctrl` / `alt` / `shift`；普通键可用
`a-z`、`0-9`、`tab`、`enter`、`esc`、`space`、`up`、`down`、`left`、`right`、`f1-f12`。

> 不支持的键会在日志里写 `unsupported`，不会让服务崩溃。

---

## 支持的平台

| 平台 | 状态 | 实现方式 | 备注 |
|---|---|---|---|
| **Windows 10 / 11** | ✅ 已在 Windows 实机验证 | `shutdown`、`rundll32`、PowerShell + `keybd_event` | 媒体键用 VK 0xAD/0xAE/0xAF/0xB0/0xB1/0xB3 |
| **macOS** | ⚠️ 代码已写，**待验证** | `osascript`（System Events） | 首次使用需在「系统设置 → 隐私与安全性 → 辅助功能」中允许终端 |
| **Linux（X11）** | ⚠️ 代码已写，**待验证** | `systemctl` + `pactl` / `xdotool` | 需装 `pulseaudio-utils`（或 pipewire-pulse）与 `xdotool` |
| **Linux（Wayland）** | ⚠️ 部分可用 | `pactl` 音量可用，`xdotool` 快捷键不行 | Wayland 下快捷键建议改用 `ydotool`（待补） |

**验证原则**：拿不准的系统调用一律写成占位函数 + 日志打印
`would run: xxx`，并在上表标为「待验证」，绝不写假代码冒充能跑。
Windows 已实机跑通；macOS / Linux 的差异请以本表为准，欢迎提 PR 补齐。

---

## 安全说明

**先读这一条：仅限可信局域网使用，不要暴露到公网。**

LanRemote 的设计假设是「你信任自己的局域网」。具体红线：

- **只监听局域网网卡**：服务绑定的是本机具体的局域网 IP（如 `192.168.1.23`），
  代码里**没有** `0.0.0.0`，也不会自动开公网端口。
  想从外网用，请自己走 VPN（如 WireGuard / Tailscale），**不要**做端口转发。
- **没有 PIN 一律拒绝**：配对前所有 WebSocket 连接直接 403；
  配对后还会校验 HMAC 签名的会话 token（绑定设备指纹 + 12 小时过期）。
- **危险操作二次确认**：关机 / 重启在前端必须点「确认执行」才会发出指令。
- **操作日志**：每次指令写一行 `logs/operations.log`，
  格式为 `时间 \t 设备指纹 \t 动作 \t 结果`。
  设备指纹是 UA 的 SHA256 短哈希，**日志里不记录 PIN、不记录 IP、不记录任何画面或按键内容**。
- **不传画面**：整个项目没有任何截图、录屏、视频编码或流传输代码。
  没有远程终端，不能执行任意 shell 命令——只认白名单里的动作名。
- **动作白名单**：`config.json` 的 `allowed_actions` 决定哪些动作可以被调用，
  不在列表里的动作服务端直接拒绝。

> PIN 是 6 位数字，理论上局域网内可以被暴力猜解。这是为「躺床上不想起身」
> 这个场景做的易用性妥协。如果你在宿舍 / 咖啡厅等不信任的网络，请先停掉服务。

---

## 目录结构

```
LanRemote/
├── lanremote.py          # 后端单文件：HTTP + 迷你 WebSocket + PIN 配对 + 平台适配 + QR
├── start.bat             # Windows 双击启动
├── start.sh              # macOS / Linux 启动（chmod +x）
├── web/
│   └── index.html        # 遥控面板前端，单文件无依赖
├── config.json           # PIN、端口、允许的动作、快捷键按钮
├── logs/
│   ├── .gitkeep
│   ├── operations.log    # 运行时生成：每次指令一行
│   └── paired_devices.json  # 运行时生成：已配对设备指纹
├── README.md
├── LICENSE               # MIT
└── .gitignore
```

运行时还会生成 `logs/` 下的两个文件，以及 Python 的 `__pycache__/`（已在 .gitignore 中忽略）。

---

## 配置

`config.json`：

```json
{
  "port": 8765,
  "pin": "482913",
  "allowed_actions": ["power_shutdown", "..."],
  "shortcut_buttons": [
    { "id": "s1", "label": "显示桌面", "cmd": "win+d" }
  ]
}
```

| 字段 | 说明 |
|---|---|
| `port` | 监听端口，默认 8765。被占用时改这里，或在 `lanremote.py` 里改默认值 |
| `pin` | 6 位数字。不是 6 位数字时启动会重新随机生成并写回本文件 |
| `allowed_actions` | 允许的动作名白名单，删掉某个就禁用对应按钮 |
| `shortcut_buttons` | 前端快捷键按钮：`id`、`label`、`cmd` |

改完 `config.json` 需要重启服务生效（前端按钮除外，刷新页面即可）。

---

## 协议

前端通过 WebSocket 连 `/ws`，发 JSON：

```json
{ "action": "media", "cmd": "volume_up" }
```

实际实现中动作名是扁平的一层，例如：

```json
{ "action": "media_volume_up" }
{ "action": "power_shutdown" }
{ "action": "shortcut_send", "cmd": "win+d" }
```

服务端回：

```json
{ "type": "result", "action": "media_volume_up", "ok": true, "detail": "ok" }
```

失败时 `ok: false`，`detail` 里是原因（如 `unsupported: ...`、`action not allowed by config`）。
前端会把对应按钮短暂标绿（成功）或标红抖动（失败），并弹一条提示。

---

## 常见问题

**Q：手机打不开地址？**
- 确认手机和电脑在同一 WiFi（不是手机流量，也不是访客网络）。
- Windows 防火墙第一次会弹窗，选「允许访问」。如果点错了，
  到「Windows Defender 防火墙 → 允许应用通过防火墙」里给 Python 打勾。
- 公司 / 学校 WiFi 常开启「AP 隔离」，设备之间互相不可见，这种情况无解，换个热点。

**Q：PIN 在哪看？**
终端启动时打印的那 6 位数字。忘了就把 `config.json` 里的 `pin` 改成任意 6 位数字再重启。

**Q：换手机了 / 想撤销配对？**
删掉 `logs/paired_devices.json` 并重启服务，所有设备需要重新输 PIN。

**Q：音量键没反应？**
Windows 上媒体键是发给「当前前台窗口」的，如果前台是某些全屏游戏可能被吃掉。
先在桌面或浏览器里试。

**Q：能加自定义命令吗？**
v0.1 故意不支持任意命令，这是安全设计。后续版本会用「白名单宏」的方式扩展。

---

## 路线图

| 版本 | 内容 | 状态 |
|---|---|---|
| **v0.1** | 电源 4 项、媒体 6 项、6 个自定义快捷键、PIN 配对、二维码、操作日志 | ✅ 当前版本 |
| **v0.2** | 宏录制：把一串按键 / 延时录成一个按钮 | 计划中 |
| **v0.3** | 语音指令：手机端浏览器语音识别 → 映射到白名单动作 | 计划中 |
| **v0.4** | 多设备分组：一个面板同时遥控多台电脑（房间分组） | 计划中 |

**明确不做**：远程桌面、屏幕画面传输、远程终端 shell、公网中继服务。
LanRemote 永远是一个「只发指令」的轻量面板。想要画面请用 RustDesk / TeamViewer。

---

## 贡献

欢迎 PR，尤其是：

- Linux（Wayland / GNOME / KDE）的媒体键与快捷键实测
- macOS 各版本 `osascript` 的行为差异
- 更多的快捷键 key 映射

补平台代码时请集中在 `lanremote.py` 的「平台适配层」区块里，
每个动作一个函数，拿不准的先写 `_would_run()` 占位并在 README 表格里标「待验证」。

---

## License

MIT License，详见 [LICENSE](LICENSE)。

Copyright (c) 2025 LanRemote contributors