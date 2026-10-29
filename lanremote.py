#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LanRemote - 轻量局域网遥控面板（后端单文件）
定位：只发指令、不传画面。不是远程桌面。
安全：只监听局域网网卡；未配对一律拒绝；每条指令写操作日志。
依赖：仅 Python 3.8+ 标准库。
"""

import base64
import hashlib
import hmac
import http.server
import ipaddress
import json
import os
import platform
import socket
import struct
import subprocess
import sys
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
LOG_DIR = os.path.join(BASE_DIR, "logs")
PAIRING_DB = os.path.join(LOG_DIR, "paired_devices.json")
OP_LOG = os.path.join(LOG_DIR, "operations.log")
SERVER_VERSION = "LanRemote/0.1"
TOKEN_TTL = 12 * 3600  # 配对成功后 token 有效期（秒）

# 全部已知动作（前端按钮/协议层与这里对齐）
KNOWN_ACTIONS = [
    "power_shutdown", "power_reboot", "power_lock", "power_sleep",
    "media_volume_up", "media_volume_down", "media_mute",
    "media_play_pause", "media_prev", "media_next",
    "shortcut_send",
]

# 快捷键 token 白名单（组合键 = 修饰键 + 普通键，用 + 连接）
MODIFIERS = {"win", "ctrl", "alt", "shift", "cmd"}
PLAIN_KEYS = set("abcdefghijklmnopqrstuvwxyz0123456789") | {
    "tab", "enter", "esc", "space", "up", "down", "left", "right",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
}

CONFIG = {}
LOG_LOCK = threading.Lock()

# ============================================================
# 日志：每条指令一行（时间、设备、动作），不记录敏感内容
# ============================================================

def op_log(device, action, detail="ok"):
    """追加一行操作日志。

    格式：时间 \t 设备指纹 \t 动作 \t 结果
    设备指纹是 UA 的短哈希——不记录 IP、PIN，也不记录任何按键内容。
    detail 会被压缩成一行并限长，避免把整条系统命令塞进日志。
    """
    detail = _short_detail(detail)
    line = "%s\t%s\t%s\t%s\n" % (
        time.strftime("%Y-%m-%d %H:%M:%S"), device, action, detail)
    with LOG_LOCK:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(OP_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    print("[log] " + line.rstrip())


def _short_detail(detail):
    """把失败详情压成适合写日志的一行短文本。"""
    if not detail:
        return "ok"
    import re
    text = re.sub(r"\s+", " ", str(detail)).strip()
    if len(text) <= 160:
        return text
    return text[:157] + "..."


# ============================================================
# 工具：网络地址探测（只挑局域网网卡，绝不猜公网）
# ============================================================

def is_private_ip(ip_str):
    """判断是否私网/链路本地地址（RFC1918 + loopback + link-local）。"""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return addr.is_private or addr.is_link_local or addr.is_loopback


def detect_lan_ip():
    """用 UDP connect 技巧拿到本机局域网出口 IP；失败返回 None。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))  # 不会真正发包，只是让路由表选网卡
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def pick_lan_ips():
    """枚举本机所有私网 IPv4，返回 (首选IP, 全部列表)。"""
    ips = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None,
                                       socket.AF_INET, socket.SOCK_STREAM):
            ip = info[4][0]
            if ip not in ips and is_private_ip(ip) and ip != "127.0.0.1":
                ips.append(ip)
    except OSError:
        pass
    primary = detect_lan_ip()
    if primary and is_private_ip(primary) and primary != "127.0.0.1":
        if primary in ips:
            ips.remove(primary)
        ips.insert(0, primary)
    return (ips[0] if ips else None), ips


# ============================================================
# 工具：终端二维码（纯文本 QR，零依赖，仅 HTTP 页面里用）
# ============================================================

# ============================================================
# 工具：纯 Python 最小二维码（QR Model 2, v2-L, byte 模式）
# 零第三方依赖。用于终端 ASCII 展示 + 网页 SVG 展示。
# ============================================================

# --- GF(256) 域运算（Reed-Solomon 纠错用），本原多项式 0x11d ---
_QR_EXP = [0] * 512
_QR_LOG = [0] * 256
_x = 1
for _i in range(255):
    _QR_EXP[_i] = _x
    _QR_LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _QR_EXP[_i] = _QR_EXP[_i - 255]


def _gf_mul(a, b):
    if a == 0 or b == 0:
        return 0
    return _QR_EXP[_QR_LOG[a] + _QR_LOG[b]]


def _rs_ec(data, ec_len):
    """对 data 计算 Reed-Solomon 纠错码。ec_len 由 QR 版本/纠错级决定。"""
    g = [1]
    for i in range(ec_len):
        ng = [0] * (len(g) + 1)
        for j, c in enumerate(g):
            ng[j] ^= c
            ng[j + 1] ^= _gf_mul(c, _QR_EXP[i])
        g = ng
    rem = [0] * ec_len
    for b in data:
        factor = b ^ rem[0]
        rem = rem[1:] + [0]
        for i in range(ec_len):
            rem[i] ^= _gf_mul(g[i + 1], factor)
    return rem


def _qr_build_matrix(text, force_mask=None):
    """把字符串编码成 25x25 QR（v2-L, byte 模式）。返回 0/1 二维列表。

    force_mask 仅供自测使用；正常路径为 None，自动挑惩罚分最低的掩码。
    """
    data = text.encode("utf-8")
    assert len(data) <= 32, "QR 内容超长（v2-L byte 模式最多 32 字节）"

    # --- 1. 位流：模式 0100 + 8 位长度 + 数据 + 终止符 ---
    bits = [0, 1, 0, 0]
    for i in range(7, -1, -1):
        bits.append((len(data) >> i) & 1)
    for byte in data:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)
    bits += [0, 0, 0, 0]
    while len(bits) % 8:
        bits.append(0)
    codewords = [int("".join(map(str, bits[i:i + 8])), 2)
                 for i in range(0, len(bits), 8)]
    pad = [0xEC, 0x11]
    i = 0
    while len(codewords) < 34:  # v2-L 数据容量 34
        codewords.append(pad[i % 2])
        i += 1
    codewords += _rs_ec(codewords, 10)  # v2-L 纠错 10 字节，共 44

    size = 25
    m = [[0] * size for _ in range(size)]
    func = [[False] * size for _ in range(size)]

    def put(x, y, v):
        m[y][x] = v
        func[y][x] = True

    def finder(cx, cy):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < size and 0 <= y < size:
                    ring = max(abs(dx), abs(dy))
                    # 环 0/1 = 3x3 实心，环 3 = 外框，环 2/4 = 白（环 4 是分隔符）
                    put(x, y, 1 if ring in (0, 1, 3) else 0)

    finder(3, 3); finder(size - 4, 3); finder(3, size - 4)
    for i in range(size):  # 时序线
        if not func[6][i]:
            put(i, 6, i % 2 == 0)
        if not func[i][6]:
            put(6, i, i % 2 == 0)
    # 对齐图形（v2 唯一有效中心 18,18）：外圈深、次圈浅、中心深
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            dist = max(abs(dx), abs(dy))
            put(18 + dx, 18 + dy, 1 if dist in (0, 2) else 0)
    put(8, size - 8, 1)  # 暗模块：第 8 列、倒数第 8 行（v2 = row 17）

    def mask_bit(mask, x, y):
        if mask == 0: return (x + y) % 2 == 0
        if mask == 1: return y % 2 == 0
        if mask == 2: return x % 3 == 0
        if mask == 3: return (x + y) % 3 == 0
        if mask == 4: return (x // 3 + y // 2) % 2 == 0
        if mask == 5: return (x * y) % 2 + (x * y) % 3 == 0
        if mask == 6: return ((x * y) % 2 + (x * y) % 3) % 2 == 0
        return ((x + y) % 2 + (x * y) % 3) % 2 == 0

    def draw_format(mask):
        """格式信息：EC=L(0b01) + 掩码号，BCH(15,5) + 0x5412。"""
        d = (0b01 << 3) | mask
        rem = d
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        fmt = ((d << 10) | rem) ^ 0x5412
        def bit(i): return (fmt >> i) & 1
        for i in range(6): put(8, i, bit(i))
        put(8, 7, bit(6)); put(8, 8, bit(7)); put(7, 8, bit(8))
        for i in range(9, 15): put(14 - i, 8, bit(i))
        for i in range(8): put(size - 1 - i, 8, bit(i))
        for i in range(8, 15): put(8, size - 15 + i, bit(i))

    def place(mask):
        """按扫描线放置数据位，跳过功能模块。

        注意：数据位用完后剩余模块（remainder bits）按主流实现的做法
        仍然要叠加掩码（bit=0 ^ mask），否则部分扫码器会读错。
        """
        grid = [row[:] for row in m]
        up = True
        col = size - 1
        idx = 0
        total = len(codewords) * 8
        while col >= 1:
            if col == 6:  # 第 6 列是竖向时序线，整列跳过
                col -= 1
            for v in range(size):
                y = size - 1 - v if up else v
                for x in (col, col - 1):
                    if func[y][x]:
                        continue
                    if idx < total:
                        bit = (codewords[idx >> 3] >> (7 - (idx & 7))) & 1
                    else:
                        bit = 0  # remainder
                    grid[y][x] = bit ^ (1 if mask_bit(mask, x, y) else 0)
                    idx += 1
            up = not up
            col -= 2
        return grid

    def penalty(grid):
        """简化惩罚评分：行/列长 run + 2x2 纯色块。"""
        p = 0
        for row in grid:
            run = 1
            for i in range(1, size):
                if row[i] == row[i - 1]:
                    run += 1
                else:
                    if run >= 5: p += 3 + (run - 5)
                    run = 1
        for x in range(size):
            run = 1
            for y in range(1, size):
                if grid[y][x] == grid[y - 1][x]:
                    run += 1
                else:
                    if run >= 5: p += 3 + (run - 5)
                    run = 1
        for y in range(size - 1):
            for x in range(size - 1):
                s = grid[y][x] + grid[y][x + 1] + grid[y + 1][x] + grid[y + 1][x + 1]
                if s in (0, 4):
                    p += 3
        return p

    if force_mask is not None:
        draw_format(force_mask)
        return place(force_mask)

    best = None
    for mask in range(8):
        draw_format(mask)
        grid = place(mask)
        score = penalty(grid)
        if best is None or score < best[0]:
            best = (score, grid)
    return best[1]


def qr_ascii(text, quiet_zone=2):
    """终端可扫的 ASCII 二维码：手机对着终端窗口扫码即可打开面板。

    黑块用 ██（2 列），白块用两个半角空格（2 列），保证等宽对齐。
    终端黑底白字时扫码器能正常识别；白底黑字终端多数扫码器支持反色。
    """
    grid = _qr_build_matrix(text)
    size = len(grid)
    lines = []
    blank = "  " * (size + quiet_zone * 2)
    lines += [blank] * quiet_zone
    for row in grid:
        line = "  " * quiet_zone
        for v in row:
            line += "██" if v else "  "
        lines.append(line + "  " * quiet_zone)
    lines += [blank] * quiet_zone
    return "\n".join(lines)


def qr_svg(text):
    """网页用 SVG 二维码（白底黑点，四周 4 模块静区）。"""
    grid = _qr_build_matrix(text)
    size = len(grid) + 8
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" '
             'shape-rendering="crispEdges">' % (size, size),
             '<rect width="100%" height="100%" fill="#fff"/>']
    for y, row in enumerate(grid):
        for x, v in enumerate(row):
            if v:
                parts.append('<rect x="%d" y="%d" width="1" height="1" fill="#111"/>' % (x + 4, y + 4))
    parts.append('</svg>')
    return "".join(parts)


# ============================================================
# 配对与安全：PIN 校验 + 设备指纹 + 会话 token
# ============================================================

def load_config():
    """读取 config.json；缺失或 PIN 不合规时用随机 6 位 PIN 顶替并写回。"""
    global CONFIG
    defaults = {
        "port": 8765,
        "pin": "",
        "allowed_actions": list(KNOWN_ACTIONS),
        "shortcut_buttons": [],
    }
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        print("[warn] 读取 config.json 失败（%s），使用默认配置" % e)
        cfg = {}
    defaults.update({k: v for k, v in cfg.items() if k in defaults})
    pin = str(defaults.get("pin", ""))
    if not (pin.isdigit() and len(pin) == 6):
        import secrets
        defaults["pin"] = str(secrets.randbelow(900000) + 100000)
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(defaults, f, ensure_ascii=False, indent=2)
        except OSError:
            pass
    defaults["port"] = int(defaults["port"])
    CONFIG = defaults
    return defaults


def load_paired():
    """读取已配对设备表 {指纹: {"exp": 过期时间戳}}。"""
    try:
        with open(PAIRING_DB, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_paired(table):
    os.makedirs(LOG_DIR, exist_ok=True)
    tmp = PAIRING_DB + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(table, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PAIRING_DB)


def device_fp(headers):
    """设备指纹 = User-Agent + Accept-Language 的 SHA256 短哈希。"""
    raw = (headers.get("User-Agent", "") + "|" +
           headers.get("Accept-Language", ""))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def issue_token(fp):
    """给已配对设备签发会话 token（HMAC 绑定指纹 + 过期时间）。"""
    payload = "%s:%d" % (fp, int(time.time()) + TOKEN_TTL)
    sig = hmac.new(CONFIG["pin"].encode(), payload.encode(),
                   hashlib.sha256).hexdigest()[:16]
    return base64.urlsafe_b64encode(("%s:%s" % (payload, sig)).encode()).decode()


def verify_token(token, fp):
    """校验 token：签名、过期时间、绑定指纹全部通过才放行。"""
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        payload, sig = decoded.rsplit(":", 1)
        fp2, exp = payload.split(":")
        if fp2 != fp or int(exp) < time.time():
            return False
        want = hmac.new(CONFIG["pin"].encode(), payload.encode(),
                        hashlib.sha256).hexdigest()[:16]
        return hmac.compare_digest(want, sig)
    except Exception:
        return False


def check_paired(fp):
    """指纹是否已配对且未过期。"""
    info = load_paired().get(fp)
    if not isinstance(info, dict):
        return False
    return int(info.get("exp", 0)) > time.time()


def pair_device(fp):
    """配对成功：记指纹 + 发 token。"""
    table = load_paired()
    table[fp] = {"exp": int(time.time()) + TOKEN_TTL}
    save_paired(table)
    return issue_token(fp)


# ============================================================
# 平台适配层：所有系统调用集中在这里，方便补 Linux/macOS
# 不支持的指令：写 unsupported 日志，绝不崩溃
# ============================================================

OS_NAME = platform.system()  # "Windows" / "Darwin" / "Linux"


def _run(cmd, shell=False, timeout=15):
    """静默执行系统命令，返回 (成功?, 输出)。

    Windows 上统一用 CREATE_NO_WINDOW，避免每次按键闪黑框。
    输出做轻量清洗：去掉 PowerShell 的 CLIXML 噪声，只保留有用信息。
    """
    try:
        r = subprocess.run(cmd, shell=shell, timeout=timeout,
                           stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           creationflags=0x08000000 if OS_NAME == "Windows" else 0)
        out = r.stdout.decode("utf-8", "replace").strip()
        return r.returncode == 0, _clean_output(out)
    except subprocess.TimeoutExpired:
        return False, "timeout: %s" % (cmd[0] if cmd else "?")
    except Exception as e:
        return False, str(e)


def _clean_output(text):
    """清掉 PowerShell 的 CLIXML 包装，避免噪声进日志和前端。

    PowerShell 在 stderr 被重定向到 stdout 时会输出 `#< CLIXML` 前缀，
    后面跟着一段 XML（含 progress 记录和错误节点）。真正的文本可能是
    普通行（如 "hello"），也可能藏在 <S S="Error">...</S> 里。
    """
    if not text:
        return text
    if "CLIXML" not in text and "<Objs" not in text:
        return text

    import re
    # 1) 去掉 CLIXML 头，以及从 <Objs 开始的整段 XML
    body = re.sub(r'#<\s*CLIXML\s*', '', text)
    xml_start = body.find("<Objs")
    plain = body[:xml_start] if xml_start >= 0 else body
    plain = plain.strip()
    if plain:
        return _unescape_clixml(plain)

    # 2) 没有普通输出，就取 XML 里的错误节点文本
    parts = re.findall(r'<S(?:\s[^>]*)?>(.*?)</S>', body, re.S)
    joined = " ".join(p.strip() for p in parts if p.strip())
    return _unescape_clixml(joined.strip()) or "ok"


def _unescape_clixml(text):
    """把 CLIXML 里的 _xXXXX_ 转义还原，并压掉多余空白。"""
    import re
    if not text:
        return text
    text = re.sub(r'_x([0-9A-Fa-f]{4})_',
                  lambda m: chr(int(m.group(1), 16)), text)
    text = re.sub(r'\s+', ' ', text).strip()
    # 错误信息里通常带一串 PowerShell 定位信息，过长就截断，日志保持一行可读
    return text if len(text) <= 200 else text[:197] + "..."


def _run_powershell(script, timeout=15):
    """执行一段 PowerShell 脚本。

    关键：用 -EncodedCommand（Base64 + UTF-16LE）传参，彻底避开
    -Command 的引号/换行/here-string 转义问题——直接在 -Command 里塞
    多行 Add-Type 会让 powershell.exe 卡住直到超时。
    """
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return _run(["powershell", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass",
                 "-EncodedCommand", encoded], timeout=timeout)


def _would_run(cmd_desc):
    """占位：打印 would run 而不是真的执行。"""
    return False, "unsupported: would run: %s" % cmd_desc


# ---- 电源类（每个动作一个函数）----

def power_shutdown():
    if OS_NAME == "Windows":
        return _run(["shutdown", "/s", "/t", "5"])
    if OS_NAME == "Darwin":
        return _run(["osascript", "-e", 'tell app "System Events" to shut down'])
    if OS_NAME == "Linux":
        return _run(["systemctl", "poweroff"])
    return _would_run("shutdown")


def power_reboot():
    if OS_NAME == "Windows":
        return _run(["shutdown", "/r", "/t", "5"])
    if OS_NAME == "Darwin":
        return _run(["osascript", "-e", 'tell app "System Events" to restart'])
    if OS_NAME == "Linux":
        return _run(["systemctl", "reboot"])
    return _would_run("reboot")


def power_lock():
    if OS_NAME == "Windows":
        return _run(["rundll32.exe", "user32.dll,LockWorkStation"])
    if OS_NAME == "Darwin":
        return _run(["osascript", "-e",
                    'tell application "System Events" to keystroke "q" '
                    'using {command down, control down}'])
    if OS_NAME == "Linux":
        for cmd in ([["loginctl", "lock-session"], ["xdg-screensaver", "lock"],
                     ["gnome-screensaver-command", "-l"]]):
            ok, out = _run(cmd)
            if ok:
                return True, out
        return False, "unsupported: no screen lock tool found"
    return _would_run("lock")


def power_sleep():
    if OS_NAME == "Windows":
        return _run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
    if OS_NAME == "Darwin":
        return _run(["osascript", "-e", 'tell app "System Events" to sleep'])
    if OS_NAME == "Linux":
        ok, out = _run(["systemctl", "suspend"])
        if ok:
            return ok, out
        return _run(["sudo", "-n", "systemctl", "suspend"])
    return _would_run("sleep")


# ---- 媒体类 ----
# Windows：无第三方依赖时，系统媒体键没有官方 CLI。
# 用 PowerShell 调 user32.dll 的 keybd_event 发顶层媒体键：
#   0xAF 音量+  0xAE 音量-  0xAD 静音
#   0xB3 播放/暂停  0xB0 下一首  0xB1 上一首
# 脚本用 -EncodedCommand 传递（见 _run_powershell），避免引号/换行转义问题。

_PS_MEDIA_HEADER = """
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class MK {
  [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
}
'@
function Send-Key([byte]$vk) {
  [MK]::keybd_event($vk, 0, 0, [UIntPtr]::Zero)
  Start-Sleep -Milliseconds 30
  [MK]::keybd_event($vk, 0, 2, [UIntPtr]::Zero)
}
"""

_PS_MEDIA = {
    "volume_up": "Send-Key 0xAF",
    "volume_down": "Send-Key 0xAE",
    "mute": "Send-Key 0xAD",
    "play_pause": "Send-Key 0xB3",
    "prev": "Send-Key 0xB1",
    "next": "Send-Key 0xB0",
}


def media_key(kind):
    """发一个媒体/音量顶层键。kind ∈ volume_up/volume_down/mute/play_pause/prev/next。"""
    if OS_NAME == "Windows":
        return _run_powershell(_PS_MEDIA_HEADER + _PS_MEDIA[kind])
    if OS_NAME == "Darwin":
        # osascript 直接调用系统媒体遥控（无需辅助功能权限的部分先试）
        script = {
            "volume_up": "set volume output volume ((output volume of (get volume settings)) + 10)",
            "volume_down": "set volume output volume ((output volume of (get volume settings)) - 10)",
            "mute": "set volume output muted (not output muted of (get volume settings))",
            "play_pause": 'tell application "System Events" to key code 49',
            "prev": 'tell application "System Events" to key code 89',
            "next": 'tell application "System Events" to key code 91',
        }[kind]
        return _run(["osascript", "-e", script])
    if OS_NAME == "Linux":
        pactl = {
            "volume_up": ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%"],
            "volume_down": ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-10%"],
            "mute": ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"],
            "play_pause": ["pactl", "send-sink-input-mute", "@DEFAULT_SINK@", "toggle"],
            "prev": None, "next": None,  # playerctl 待补
        }.get(kind)
        if pactl:
            return _run(pactl)
        # 回退到 xdotool（若装了）
        xdo = {"play_pause": "XF86AudioPlay", "prev": "XF86AudioPrev",
               "next": "XF86AudioNext", "volume_up": "XF86AudioRaiseVolume",
               "volume_down": "XF86AudioLowerVolume", "mute": "XF86AudioMute"}
        ok, out = _run(["xdotool", "key", xdo[kind]])
        if ok:
            return ok, out
        return False, "unsupported: install pactl or xdotool for media keys"
    return _would_run("media " + kind)


def media_volume_up():
    return media_key("volume_up")


def media_volume_down():
    return media_key("volume_down")


def media_mute():
    return media_key("mute")


def media_play_pause():
    return media_key("play_pause")


def media_prev():
    return media_key("prev")


def media_next():
    return media_key("next")


# ---- 快捷键 ----

def shortcut_send(cmd):
    """发组合键。cmd 形如 "win+d" / "alt+tab"，token 白名单校验。"""
    keys = [k.strip().lower() for k in cmd.split("+") if k.strip()]
    if not keys or any(k not in MODIFIERS and k not in PLAIN_KEYS for k in keys):
        return False, "invalid shortcut tokens"
    mods = [k for k in keys if k in MODIFIERS]
    plain = [k for k in keys if k not in MODIFIERS]
    if len(plain) > 1 or not plain:
        return False, "shortcut needs exactly one non-modifier key"
    plain = plain[0]

    if OS_NAME == "Windows":
        # VK 码映射 + PowerShell keybd_event
        vk = {"win": 0x5B, "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "cmd": 0x5B}
        single = {}
        for c in "abcdefghijklmnopqrstuvwxyz0123456789":
            single[c] = ord(c.upper())
        named = {"tab": 0x09, "enter": 0x0D, "esc": 0x1B, "space": 0x20,
                 "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27}
        for i in range(1, 13):
            named["f%d" % i] = 0x6F + i  # F1=0x70
        if plain in single:
            vk_plain = single[plain]
        elif plain in named:
            vk_plain = named[plain]
        else:
            return False, "unsupported key on Windows"
        vks = [vk[m] for m in mods] + [vk_plain]
        # 按下所有修饰键 → 按主键 → 逆序松开
        presses = "".join(
            "[MK]::keybd_event(%d,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 40;" % v
            for v in vks)
        releases = "".join(
            "[MK]::keybd_event(%d,0,2,[UIntPtr]::Zero);Start-Sleep -Milliseconds 20;" % v
            for v in reversed(vks))
        return _run_powershell(_PS_MEDIA_HEADER + presses + releases)
    if OS_NAME == "Darwin":
        mac_mod = {"win": "command down", "cmd": "command down",
                   "ctrl": "control down", "alt": "option down", "shift": "shift down"}
        code = {"tab": 48, "enter": 36, "esc": 53, "space": 49,
                "up": 126, "down": 125, "left": 123, "right": 124}
        for i in range(1, 13):
            code["f%d" % i] = 63 + i  # F1=64
        if plain in "abcdefghijklmnopqrstuvwxyz0123456789":
            key_part = 'keystroke "%s"' % plain
        elif plain in code:
            key_part = 'key code %d' % code[plain]
        else:
            return False, "unsupported key on macOS"
        mods_part = " using {%s}" % ", ".join(mac_mod[m] for m in mods) if mods else ""
        script = 'tell application "System Events" to %s%s' % (key_part, mods_part)
        return _run(["osascript", "-e", script])
    if OS_NAME == "Linux":
        xdo_mod = {"win": "super", "cmd": "super", "ctrl": "ctrl",
                   "alt": "alt", "shift": "shift"}
        key_name = plain if plain not in ("tab", "enter", "esc", "space",
                                           "up", "down", "left", "right") else {
            "tab": "Tab", "enter": "Return", "esc": "Escape", "space": "space",
            "up": "Up", "down": "Down", "left": "Left", "right": "Right"}[plain]
        arg = "+".join([xdo_mod[m] for m in mods] + [key_name])
        ok, out = _run(["xdotool", "key", arg])
        if ok:
            return ok, out
        return False, "unsupported: install xdotool for shortcuts"
    return _would_run("shortcut " + cmd)


# 动作名 → 执行函数 的分派表（避免巨型 if-else）
ACTION_TABLE = {
    "power_shutdown": lambda: power_shutdown(),
    "power_reboot": lambda: power_reboot(),
    "power_lock": lambda: power_lock(),
    "power_sleep": lambda: power_sleep(),
    "media_volume_up": lambda: media_volume_up(),
    "media_volume_down": lambda: media_volume_down(),
    "media_mute": lambda: media_mute(),
    "media_play_pause": lambda: media_play_pause(),
    "media_prev": lambda: media_prev(),
    "media_next": lambda: media_next(),
}


def execute_action(action, payload=None):
    """执行一个动作。返回 (成功?, 详情)。未支持/未在白名单均不崩溃。"""
    if action not in CONFIG.get("allowed_actions", []):
        return False, "action not allowed by config"
    if action == "shortcut_send":
        cmd = str((payload or {}).get("cmd", ""))
        return shortcut_send(cmd)
    fn = ACTION_TABLE.get(action)
    if fn is None:
        return False, "unsupported: no handler for %s" % action
    return fn()


# ============================================================
# HTTP + WebSocket 服务
# 安全：bind 到具体局域网 IP（绝不用 0.0.0.0）；未配对一律 403
# ============================================================

# --- 极简 WebSocket（RFC6455 服务端最小实现：文本帧足够）---

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
WS_CLIENTS = {}  # fp -> {"conn": conn, "last_seen": ts}
WS_LOCK = threading.Lock()


def ws_accept_key(sec_key):
    sha = hashlib.sha1((sec_key + WS_GUID).encode()).digest()
    return base64.b64encode(sha).decode()


def ws_handshake(handler):
    """在 http.server 处理器里完成 101 升级。成功返回 True。"""
    key = handler.headers.get("Sec-WebSocket-Key")
    if not key:
        return False
    resp = ("HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Accept: %s\r\n\r\n" % ws_accept_key(key))
    handler.connection.sendall(resp.encode())
    return True


def ws_send_text(conn, text):
    """发送文本帧（服务端帧不掩码，单帧搞定）。"""
    data = text.encode("utf-8")
    header = bytearray([0x81])  # FIN + text opcode
    n = len(data)
    if n < 126:
        header.append(n)
    elif n < 65536:
        header.append(126)
        header += n.to_bytes(2, "big")
    else:
        header.append(127)
        header += n.to_bytes(8, "big")
    conn.sendall(bytes(header) + data)


def ws_recv_text(conn):
    """收一个文本帧；返回 str，连接关闭/协议错误返回 None。"""
    try:
        hdr = _recv_exact(conn, 2)
        if not hdr:
            return None
        opcode = hdr[0] & 0x0F
        n = hdr[1] & 0x7F
        masked = hdr[1] & 0x80
        if n == 126:
            ext = _recv_exact(conn, 2)
            if not ext:
                return None
            n = int.from_bytes(ext, "big")
        elif n == 127:
            ext = _recv_exact(conn, 8)
            if not ext:
                return None
            n = int.from_bytes(ext, "big")
        if n > 1 << 20:  # 1MB 上限，防滥用
            return None
        mask = _recv_exact(conn, 4) if masked else None
        data = _recv_exact(conn, n)
        if data is None:
            return None
        if mask:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        if opcode == 0x8:  # close 帧
            return None
        if opcode == 0x9:  # ping → 回 pong
            try:
                conn.sendall(bytes([0x8A, 0x00]))
            except OSError:
                return None
            return ""
        if opcode != 0x1:  # 只收文本帧
            return None
        return data.decode("utf-8", "replace")
    except (OSError, struct.error):
        return None


def _recv_exact(conn, n):
    """精确收 n 字节；对端关闭返回 None。"""
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def ws_thread(handler, fp):
    """配对成功后每条连接的收发循环：只处理 JSON 指令。"""
    conn = handler.connection
    addr = handler.client_address[0]
    with WS_LOCK:
        WS_CLIENTS[fp] = conn
    try:
        while True:
            raw = ws_recv_text(conn)
            if raw is None:
                break
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                ws_send_text(conn, json.dumps({"type": "error", "detail": "bad json"}))
                continue
            action = msg.get("action", "")
            # 危险操作二次确认由前端负责弹窗；服务端收到才执行
            ok, detail = execute_action(action, msg)
            op_log(fp, action, "ok" if ok else detail)
            ws_send_text(conn, json.dumps({
                "type": "result", "action": action,
                "ok": ok, "detail": detail if not ok else "ok"}))
    finally:
        with WS_LOCK:
            if WS_CLIENTS.get(fp) is conn:
                del WS_CLIENTS[fp]
        try:
            conn.close()
        except OSError:
            pass


# --- HTTP 处理器 ---

INDEX_PATH = os.path.join(BASE_DIR, "web", "index.html")


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = SERVER_VERSION
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # 静默默认访问日志，只留操作日志

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode())

    # ---- GET ----
    def do_GET(self):
        path = self.path.split("?")[0]
        # ---- WebSocket 升级（浏览器握手发的是 GET，不是 POST）----
        if path == "/ws":
            if self.headers.get("Upgrade", "").lower() != "websocket":
                self._json(400, {"ok": False, "detail": "expected websocket"})
                return
            fp = device_fp(self.headers)
            # 安全红线：未配对一律拒绝 WebSocket
            if not check_paired(fp):
                op_log(fp, "ws_connect", "rejected: not paired")
                self._json(403, {"ok": False, "detail": "not paired"})
                return
            if not ws_handshake(self):
                return
            ws_thread(self, fp)
            return
        if path in ("/", "/index.html"):
            try:
                with open(INDEX_PATH, "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except OSError:
                self._send(404, b"index.html missing")
            return
        if path == "/qr.svg":
            ip, _ = pick_lan_ips()
            url = "http://%s:%d" % (ip or "127.0.0.1", CONFIG["port"])
            self._send(200, qr_svg(url).encode(), "image/svg+xml")
            return
        if path == "/api/pair":
            # 检查指纹：已配对则直接发 token，跳过 PIN
            fp = device_fp(self.headers)
            if check_paired(fp):
                self._json(200, {"ok": True, "token": pair_device(fp)})
            else:
                self._json(200, {"ok": False, "need_pin": True})
            return
        if path == "/api/ping":
            self._json(200, {"ok": True, "version": SERVER_VERSION,
                             "os": OS_NAME})
            return
        if path == "/api/config":
            # 只回显前端需要的展示信息，不含 PIN/路径等敏感项
            self._json(200, {
                "ok": True,
                "os": OS_NAME,
                "os_release": platform.release(),
                "shortcut_buttons": CONFIG.get("shortcut_buttons", []),
                "allowed_actions": CONFIG.get("allowed_actions", []),
            })
            return
        self._json(404, {"ok": False, "detail": "not found"})

    # ---- POST ----
    def do_POST(self):
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(min(length, 1 << 20))
        if path == "/api/pair":
            fp = device_fp(self.headers)
            try:
                data = json.loads(body.decode("utf-8"))
            except ValueError:
                self._json(400, {"ok": False, "detail": "bad json"})
                return
            if not check_paired(fp) and data.get("pin") != CONFIG["pin"]:
                op_log(fp, "pair", "wrong pin")
                self._json(403, {"ok": False, "detail": "wrong pin"})
                return
            token = pair_device(fp)
            op_log(fp, "pair", "ok")
            self._json(200, {"ok": True, "token": token})
            return
        # 其余 POST 路径一律要求已配对
        fp = device_fp(self.headers)
        if not check_paired(fp):
            self._json(403, {"ok": False, "detail": "not paired"})
            return
        self._json(404, {"ok": False, "detail": "not found"})


# ============================================================
# main
# ============================================================

def main():
    load_config()
    os.makedirs(LOG_DIR, exist_ok=True)
    ip, ips = pick_lan_ips()
    if not ip:
        print("[fatal] 未找到局域网网卡地址，退出。请先连接 WiFi/网线。")
        sys.exit(1)
    port = CONFIG["port"]
    url = "http://%s:%d" % (ip, port)

    try:
        srv = http.server.ThreadingHTTPServer((ip, port), Handler)
    except OSError as e:
        print("[fatal] 绑定 %s:%d 失败：%s" % (ip, port, e))
        sys.exit(1)

    print("=" * 56)
    print("  LanRemote v0.1  躺在沙发上，用手机指挥电脑")
    print("=" * 56)
    print("  本机地址 : %s" % url)
    if len(ips) > 1:
        print("  其他网卡 : %s" % ", ".join(ips[1:]))
    print("  配对 PIN  : %s" % CONFIG["pin"])
    print("  平台      : %s (%s)" % (OS_NAME, platform.release()))
    print("-" * 56)
    print(qr_ascii(url))
    print("-" * 56)
    print("  手机与电脑连同一 WiFi，扫码或浏览器打开上面地址，")
    print("  首次连接输入 6 位 PIN。Ctrl+C 退出。")
    print("  仅限可信局域网使用，不要暴露到公网。")
    print("=" * 56)

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[exit] 收到 Ctrl+C，关闭服务。")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
