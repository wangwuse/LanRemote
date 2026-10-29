#!/usr/bin/env bash
# LanRemote v0.1 - 局域网遥控面板（macOS / Linux 启动脚本）
# 用法：chmod +x start.sh && ./start.sh
set -u

# 切到脚本所在目录，双击/从别处调用都能找对文件
cd "$(dirname "$0")" || exit 1

echo "============================================================"
echo "  LanRemote v0.1  -  局域网遥控面板"
echo "============================================================"
echo

# ---- 查找 Python 3 ----
PY=""
for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
        if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
            PY="$cand"
            break
        fi
    fi
done

if [ -z "$PY" ]; then
    echo "[错误] 没有找到 Python 3.8+。"
    echo
    case "$(uname -s)" in
        Darwin) echo "  macOS 安装方法： brew install python3   （或到 python.org 下载安装包）" ;;
        *)      echo "  Debian/Ubuntu： sudo apt install python3" ;
                echo "  Fedora/RHEL：   sudo dnf install python3" ;
                echo "  Arch：          sudo pacman -S python" ;;
    esac
    echo
    echo "  LanRemote 只需要标准库，装好 Python 后无需 pip install。"
    echo
    read -r -p "按回车退出..." _
    exit 1
fi

echo "[信息] 使用 Python：$PY ($("$PY" -c 'import sys; print(sys.version.split()[0])'))"

# ---- macOS 提示：媒体键需要辅助功能权限 ----
if [ "$(uname -s)" = "Darwin" ]; then
    echo "[提示] macOS 上首次使用快捷键/媒体键，需在"
    echo "       系统设置 > 隐私与安全性 > 辅助功能 中允许 终端/iTerm。"
    echo
fi

# ---- Linux 依赖提示（缺失不阻塞，只是对应动作会 unsupported）----
if [ "$(uname -s)" = "Linux" ]; then
    command -v pactl   >/dev/null 2>&1 || echo "[提示] 未检测到 pactl（音量控制），可安装 pulseaudio-utils 或 pipewire-pulse。"
    command -v xdotool >/dev/null 2>&1 || echo "[提示] 未检测到 xdotool（快捷键发射），可安装 xdotool。"
    echo
fi

echo "[信息] 正在启动服务，按 Ctrl+C 可停止。"
echo

"$PY" ./lanremote.py
CODE=$?

echo
if [ "$CODE" -ne 0 ]; then
    echo "[错误] 服务异常退出，代码 $CODE。请把上面的报错信息反馈给作者。"
else
    echo "[信息] 服务已停止。"
fi

# 交互式终端里才等待，避免 CI/后台运行时卡住
if [ -t 0 ]; then
    read -r -p "按回车退出..." _
fi
exit "$CODE"