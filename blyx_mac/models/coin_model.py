"""刷金逻辑：默认 BOSS 循环 + 自定义脚本解释器。"""

from __future__ import annotations

import math
import time
from typing import Callable, Optional

from ..engine import MacEngine

LogFn = Callable[[str], None]


class CoinModel:
    def __init__(
        self,
        engine: MacEngine,
        config: dict,
        log: LogFn,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.engine = engine
        self.config = config
        self.log = log
        self.should_stop = should_stop or (lambda: False)
        self._start_ts = 0.0

    def _stop(self) -> bool:
        return self.should_stop()

    def _sleep(self, sec: float) -> None:
        end = time.time() + sec
        while time.time() < end:
            if self._stop():
                return
            time.sleep(min(0.1, end - time.time()))

    def ensure_window(self) -> bool:
        kws = self.config.get("window_title_keywords") or ["百炼英雄"]
        win = self.engine.find_window(kws)
        if not win:
            self.log("未找到游戏窗口")
            return False
        self.log(f"已绑定窗口: [{win.owner}] {win.title or '(无标题)'}")
        return True

    def check_time_limits(self) -> bool:
        coins = self.config.get("coins", {})
        start_min = int(coins.get("start_min") or 0)
        end_min = int(coins.get("end_min") or 0)
        restart_min = int(coins.get("restart_min") or 0)
        elapsed_min = (time.time() - self._start_ts) / 60.0
        if start_min > 0 and elapsed_min < start_min:
            remain = start_min - elapsed_min
            self.log(f"脚本将在 {remain:.1f} 分钟后开始")
            self._sleep(min(30, remain * 60))
            return not self._stop()
        if end_min > 0 and elapsed_min >= end_min:
            self.log("达到结束时间，停止脚本")
            return False
        if restart_min > 0 and elapsed_min > 0 and int(elapsed_min) % restart_min == 0:
            # 轻量提示；Mac 版不做强制杀进程重启
            self.log("已达到重启时间点（Mac 版请手动刷新游戏页）")
        return True

    def open_chest_if_any(self) -> None:
        for name in ("baoxiang", "bx", "lingqu", "jiangli2"):
            if self.engine.click_pic(name, threshold=0.78):
                self.log(f"发现宝箱/奖励，点击 {name}")
                self._sleep(0.6)
                return

    def go_city(self) -> None:
        # 没有稳定城内模板时，尝试 back / 常见返回
        for name in ("back", "jjcfanhui", "cxjr"):
            if self.engine.click_pic(name, threshold=0.75):
                self.log("执行回城/返回")
                self._sleep(0.8)
                return
        self.log("未找到回城控件，跳过")

    def teleport_boss(self, name: str) -> bool:
        """打开传送面板后点列表估计行；可用配置 coins.teleport_rows 覆盖。"""
        self.log(f"尝试传送: {name}")
        opened = False
        th = float(self.config.get("threshold", 0.82)) - 0.05
        for tpl in ("cs", "cs1", "cs2", "cs3", "cs4", "cslb"):
            if self.engine.click_pic(tpl, threshold=max(0.65, th)):
                opened = True
                self._sleep(0.6)
                break
        if not opened:
            self.log("未找到传送入口模板（cs/cs1..），请到校准页测模板")
            return False
        win = self.engine.bind_window
        if not win:
            return False
        # 可选：config['coins']['teleport_rows'] = {"疯牛魔王": [x,y], ...}
        rows = (self.config.get("coins") or {}).get("teleport_rows") or {}
        if name in rows and isinstance(rows[name], (list, tuple)) and len(rows[name]) >= 2:
            x, y = int(rows[name][0]), int(rows[name][1])
            self.engine.click(x, y)
            self.log(f"传送 {name} 使用配置坐标 ({x},{y})")
        else:
            order = list((self.config.get("coins") or {}).get("default_bosses") or [])
            if name in order:
                row = order.index(name) + 1
            else:
                row = (sum(ord(c) for c in name) % 5) + 1
            x = win.width // 2
            y = int(win.height * (0.30 + 0.08 * row))
            self.engine.click(x, y)
            self.log(f"已点击传送列表估计行 {row} @({x},{y})（校准页取点后可写入 teleport_rows）")
        self._sleep(1.0)
        # 确认进入：尝试点一次 ok
        self.engine.click_pic("ok", threshold=0.72)
        self.engine.click_pic("ok2", threshold=0.72)
        return True

    def move_dir(self, direction: str, seconds: float) -> None:
        win = self.engine.bind_window
        if not win:
            return
        cx, cy = win.width // 2, int(win.height * 0.62)
        dist = 120
        mapping = {
            "上": (0, -dist),
            "下": (0, dist),
            "左": (-dist, 0),
            "右": (dist, 0),
            "左上": (-dist, -dist),
            "右上": (dist, -dist),
            "左下": (-dist, dist),
            "右下": (dist, dist),
        }
        dx, dy = mapping.get(direction, (dist, dist))
        self.log(f"移动 {direction} {seconds}s")
        # 通过按住滑动模拟摇杆
        steps = max(1, int(seconds / 0.2))
        for _ in range(steps):
            if self._stop():
                return
            self.engine.swipe(cx, cy, cx + dx, cy + dy, duration=0.18, steps=8)
            self._sleep(0.05)

    def do_script_line(self, line: str) -> bool:
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("注释"):
            return True
        parts = s.split()
        cmd = parts[0]
        if cmd == "等待":
            sec = float(parts[1]) if len(parts) > 1 else 1.0
            self.log(f"等待 {sec}s")
            self._sleep(sec)
        elif cmd == "传送":
            name = parts[1] if len(parts) > 1 else ""
            self.teleport_boss(name)
        elif cmd == "移动":
            direction = parts[1] if len(parts) > 1 else "右下"
            sec = float(parts[2]) if len(parts) > 2 else 1.0
            self.move_dir(direction, sec)
        elif cmd == "回城":
            self.go_city()
        elif cmd == "开宝箱":
            self.open_chest_if_any()
        elif cmd == "点击":
            if len(parts) >= 3:
                x, y = int(parts[1]), int(parts[2])
                self.engine.click(x, y)
                self.log(f"点击坐标 {x},{y}")
        elif cmd == "重启":
            self.log("重启指令：Mac 版请手动刷新网页/小程序")
            self._sleep(2)
        elif cmd == "停止":
            self.log("脚本遇到停止指令")
            return False
        elif cmd == "跳转":
            # 由解释器处理
            return True
        else:
            self.log(f"未知指令: {s}")
        return True

    def run_custom(self) -> None:
        script = self.config.get("coins", {}).get("custom_script") or ""
        lines = script.splitlines()
        if not any(l.strip() and not l.strip().startswith("#") for l in lines):
            self.log("未配置脚本")
            return
        self.log("开始执行自定义模式")
        i = 0
        while i < len(lines) and not self._stop():
            if not self.check_time_limits():
                break
            line = lines[i].strip()
            if line.startswith("跳转"):
                parts = line.split()
                try:
                    target = int(parts[1]) - 1
                    if 0 <= target < len(lines):
                        self.log(f"跳转到第 {target + 1} 行")
                        i = target
                        continue
                except Exception:
                    self.log("跳转指令有误，格式应为: 跳转 数字")
            if not self.do_script_line(line):
                break
            i += 1
            # 循环执行
            if i >= len(lines):
                i = 0
                self._sleep(0.5)

    def run_default(self) -> None:
        bosses = self.config.get("coins", {}).get("selected_bosses") or []
        if not bosses:
            self.log("请至少选择一个默认 BOSS")
            return
        self.log(f"开始执行默认模式: {', '.join(bosses)}")
        while not self._stop():
            if not self.check_time_limits():
                break
            for boss in bosses:
                if self._stop():
                    break
                self.teleport_boss(boss)
                self._sleep(1.0)
                self.move_dir("右下", 2.5)
                self.open_chest_if_any()
                self._sleep(0.8)
                self.go_city()
                self._sleep(1.0)

    def run_coins(self) -> None:
        self.log("开始刷金")
        if not self.ensure_window():
            return
        self._start_ts = time.time()
        mode = self.config.get("coins", {}).get("mode") or "default"
        try:
            if mode == "custom":
                self.run_custom()
            else:
                self.run_default()
        except Exception as e:
            self.log(f"刷金异常: {e}")
        self.log("刷金脚本已停止")


def angle_to_radians(angle: float) -> float:
    return angle * math.pi / 180.0


def calc_end_point(cx: float, cy: float, radius: float, angle: float) -> tuple[float, float]:
    rad = angle_to_radians(angle)
    return cx + radius * math.cos(rad), cy + radius * math.sin(rad)
