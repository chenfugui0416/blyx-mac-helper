#!/usr/bin/env bash
# 打包 macOS .app（PyInstaller）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
echo "[*] using $PY"
"$PY" -m pip install -U pyinstaller pillow opencv-python-headless mss pynput pyobjc-framework-Quartz pyobjc-framework-Cocoa

ICON_SRC="$ROOT/blyx_mac/assets/images/blyx.ico"
ICON_ICNS="$ROOT/build_assets/blyx.icns"
mkdir -p "$ROOT/build_assets" "$ROOT/dist"

# 简易 icns：若 sips/iconutil 可用则转换，否则无 icon
if [[ -f "$ICON_SRC" ]]; then
  TMP="$ROOT/build_assets/blyx.iconset"
  rm -rf "$TMP"
  mkdir -p "$TMP"
  # ico 可能无法直接转；用 png 兜底
  PNG="$ROOT/blyx_mac/assets/images/ok2.png"
  if command -v sips >/dev/null 2>&1; then
    for s in 16 32 128 256 512; do
      sips -z $s $s "$PNG" --out "$TMP/icon_${s}x${s}.png" >/dev/null
      sips -z $((s*2)) $((s*2)) "$PNG" --out "$TMP/icon_${s}x${s}@2x.png" >/dev/null 2>&1 || true
    done
    iconutil -c icns "$TMP" -o "$ICON_ICNS" 2>/dev/null || true
  fi
fi

ARGS=(
  --noconfirm
  --windowed
  --name "百炼英雄Mac"
  --paths "$ROOT"
  --add-data "blyx_mac/assets/images:blyx_mac/assets/images"
  --hidden-import pynput.keyboard._darwin
  --hidden-import pynput.mouse._darwin
  --hidden-import Quartz
  --collect-submodules blyx_mac
)

if [[ -f "$ICON_ICNS" ]]; then
  ARGS+=(--icon "$ICON_ICNS")
fi

"$PY" -m PyInstaller "${ARGS[@]}" "$ROOT/main.py"

echo "[+] done: $ROOT/dist/百炼英雄Mac.app"
echo "    首次运行若被拦：右键打开，并授予 屏幕录制/辅助功能 权限给该 App"
