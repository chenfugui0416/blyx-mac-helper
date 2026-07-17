"""键盘方向录制（对齐原版 listen_mouse 输出格式）。"""

from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from typing import Callable, Optional

try:
    from pynput import keyboard
except Exception:  # pragma: no cover
    keyboard = None

from ..engine import MacEngine

DIR_KEYS = {
    "up": "上",
    "down": "下",
    "left": "左",
    "right": "右",
    "w": "上",
    "s": "下",
    "a": "左",
    "d": "右",
}


def combine_dirs(pressed: set[str]) -> Optional[str]:
    has_u = "上" in pressed
    has_d = "下" in pressed
    has_l = "左" in pressed
    has_r = "右" in pressed
    if has_u and has_l:
        return "左上"
    if has_u and has_r:
        return "右上"
    if has_d and has_l:
        return "左下"
    if has_d and has_r:
        return "右下"
    if has_u:
        return "上"
    if has_d:
        return "下"
    if has_l:
        return "左"
    if has_r:
        return "右"
    return None


class KeyMonitor:
    def __init__(self, on_line: Callable[[str], None], min_sec: float = 0.15) -> None:
        self.on_line = on_line
        self.min_sec = min_sec
        self._listener: Optional[keyboard.Listener] = None
        self._pressed: set[str] = set()
        self._dir: Optional[str] = None
        self._dir_t0 = 0.0
        self._last_release = 0.0
        self._lock = threading.Lock()
        self.running = False

    def start(self) -> bool:
        if keyboard is None:
            return False
        if self.running:
            return True
        self.running = True
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.daemon = True
        self._listener.start()
        return True

    def stop(self) -> None:
        self.running = False
        self._flush(force=True)
        if self._listener:
            self._listener.stop()
            self._listener = None

    def _key_name(self, key) -> Optional[str]:
        try:
            if hasattr(key, "char") and key.char:
                return key.char.lower()
            name = str(key).replace("Key.", "").lower()
            return name
        except Exception:
            return None

    def _on_press(self, key) -> None:
        if not self.running:
            return
        name = self._key_name(key)
        if not name or name not in DIR_KEYS:
            return
        d = DIR_KEYS[name]
        with self._lock:
            if d in self._pressed:
                return
            self._pressed.add(d)
            new_dir = combine_dirs(self._pressed)
            if new_dir != self._dir:
                self._flush(force=False)
                self._dir = new_dir
                self._dir_t0 = time.time()

    def _on_release(self, key) -> None:
        if not self.running:
            return
        name = self._key_name(key)
        if not name or name not in DIR_KEYS:
            return
        d = DIR_KEYS[name]
        with self._lock:
            self._pressed.discard(d)
            new_dir = combine_dirs(self._pressed)
            if new_dir != self._dir:
                self._flush(force=False)
                self._dir = new_dir
                self._dir_t0 = time.time() if new_dir else 0.0
            # 松开后若有间隔，可记等待
            now = time.time()
            if self._last_release and now - self._last_release > 0.8 and not self._pressed:
                wait = now - self._last_release
                if wait >= self.min_sec:
                    self.on_line(f"等待 {wait:.2f}")
            self._last_release = now

    def _flush(self, force: bool = False) -> None:
        if not self._dir or self._dir_t0 <= 0:
            return
        dur = time.time() - self._dir_t0
        if dur >= self.min_sec or force:
            if dur >= self.min_sec:
                self.on_line(f"移动 {self._dir} {dur:.2f}")
        self._dir = None
        self._dir_t0 = 0.0


class RecorderPanel(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        engine: MacEngine,
        log: Callable[[str], None],
        apply_script: Callable[[str], None],
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        self.engine = engine
        self.log = log
        self.apply_script = apply_script
        self.monitor = KeyMonitor(self._append_line)
        self._build()

    def _build(self) -> None:
        tip = (
            "录制说明：开始后切换到游戏窗口，用 ↑↓←→ 或 WASD 移动；松手结算「移动 方向 秒数」。\n"
            "录制时鼠标不要挡在游戏窗上。可用下方按钮插入等待/点击/开宝箱/回城/传送等。"
        )
        ttk.Label(self, text=tip, justify=tk.LEFT).pack(anchor=tk.W, padx=8, pady=6)

        bar = ttk.Frame(self)
        bar.pack(fill=tk.X, padx=8, pady=4)
        self.btn_toggle = ttk.Button(bar, text="开始录制", command=self.toggle)
        self.btn_toggle.pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="插入等待1s", command=lambda: self._append_line("等待 1.00")).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="插入开宝箱", command=lambda: self._append_line("开宝箱")).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="插入回城", command=lambda: self._append_line("回城")).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="插入点击中心", command=self.insert_center_click).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="清空", command=self.clear).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="复制", command=self.copy).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="写入金币自定义脚本", command=self.apply_to_coin).pack(side=tk.LEFT, padx=2)

        self.lbl_state = ttk.Label(self, text="状态: 就绪")
        self.lbl_state.pack(anchor=tk.W, padx=8)

        self.txt = scrolledtext.ScrolledText(self, height=18, font=("Menlo", 12))
        self.txt.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)
        self.txt.insert(
            tk.END,
            "# 录制脚本\n"
            "# 支持：传送 名称 | 移动 方向 秒 | 等待 秒 | 回城 | 开宝箱 | 点击 x y | 重启 | 停止 | 跳转 行号\n",
        )

    def _append_line(self, line: str) -> None:
        def _do() -> None:
            self.txt.insert(tk.END, line.rstrip() + "\n")
            self.txt.see(tk.END)
            self.log(f"录制: {line}")

        # pynput 回调在后台线程
        try:
            self.after(0, _do)
        except Exception:
            _do()

    def toggle(self) -> None:
        if self.monitor.running:
            self.monitor.stop()
            self.btn_toggle.configure(text="开始录制")
            self.lbl_state.configure(text="状态: 已停止")
            self.log("录制已停止")
            return
        if keyboard is None:
            messagebox.showerror("错误", "pynput 不可用")
            return
        ok = self.monitor.start()
        if not ok:
            messagebox.showerror("错误", "无法启动键盘监听，请检查辅助功能权限")
            return
        self.btn_toggle.configure(text="停止录制")
        self.lbl_state.configure(text="状态: 录制中（方向键/WASD）")
        self.log("开始录制")

    def clear(self) -> None:
        self.txt.delete("1.0", tk.END)
        self.txt.insert(
            tk.END,
            "# 录制脚本\n"
            "# 支持：传送 名称 | 移动 方向 秒 | 等待 秒 | 回城 | 开宝箱 | 点击 x y | 重启 | 停止 | 跳转 行号\n",
        )

    def copy(self) -> None:
        text = self.txt.get("1.0", tk.END)
        self.clipboard_clear()
        self.clipboard_append(text)
        self.log("脚本已复制到剪贴板")

    def apply_to_coin(self) -> None:
        self.apply_script(self.txt.get("1.0", tk.END))

    def insert_center_click(self) -> None:
        win = self.engine.bind_window
        if not win:
            messagebox.showwarning("提示", "请先在校准页绑定窗口，以便写入相对坐标")
            return
        x, y = win.width // 2, int(win.height * 0.62)
        self._append_line(f"点击 {x} {y}")
