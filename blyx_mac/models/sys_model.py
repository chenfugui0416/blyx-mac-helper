"""系统功能：竞技场循环（对齐 sys_model 骨架）。"""

from __future__ import annotations

import random
import time
from typing import Callable, Optional

from ..engine import MacEngine

LogFn = Callable[[str], None]


class SysModel:
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

    def in_jjc_ui(self) -> bool:
        return self.engine.ishas("jjcui", threshold=0.75) or self.engine.ishas("jjcvs", threshold=0.75)

    def run_jjc(self) -> None:
        cfg = self.config.get("sys", {})
        max_count = int(cfg.get("jjc_count") or 10)
        random_btn = bool(cfg.get("random_btn", True))
        self.log("开始运行竞技场")
        if not self.ensure_window():
            return
        done = 0
        while not self._stop() and done < max_count:
            if not self.in_jjc_ui():
                # 尝试点竞技场入口模板（若有）
                for name in ("jjcui", "jjcvs"):
                    if self.engine.click_pic(name, threshold=0.72):
                        break
                if not self.engine.wait_pic("jjcui", timeout=5) and not self.engine.wait_pic("jjcvs", timeout=1):
                    self.log("未检测到竞技场主界面")
                    self._sleep(1.5)
                    continue
            self.log(f"当前第 {done + 1}/{max_count} 场")
            # 开始挑战：无稳定按钮图时点中下部
            started = False
            for name in ("jjcvs", "ok", "ok2"):
                if self.engine.click_pic(name, threshold=0.72):
                    started = True
                    break
            if not started:
                win = self.engine.bind_window
                if win:
                    # 随机偏移，模拟原版 random_btn
                    ox = random.randint(-20, 20) if random_btn else 0
                    oy = random.randint(-8, 8) if random_btn else 0
                    self.engine.click(win.width // 2 + ox, int(win.height * 0.78) + oy)
            self.log("开始挑战")
            # 等待结束
            deadline = time.time() + 90
            while time.time() < deadline and not self._stop():
                if self.engine.ishas("jjcfanhui", threshold=0.75) or self.engine.ishas("back", threshold=0.75):
                    break
                # 战斗中可点自动等，这里仅等待
                self._sleep(1.0)
            # 返回
            for name in ("jjcfanhui", "back", "ok", "ok2"):
                if self.engine.click_pic(name, threshold=0.72):
                    break
            done += 1
            self.log(f"挑战结束，已挑战 {done}")
            self._sleep(1.2)
        self.log("竞技场流程结束")

    def run_sys_model(self) -> None:
        self.run_jjc()
