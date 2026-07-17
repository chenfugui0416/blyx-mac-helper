"""抽卡 / 招募逻辑（对齐原版 card_model 行为骨架，补强分支）。"""

from __future__ import annotations

import time
from typing import Callable, Optional

from ..config import COLOR_CN, COLOR_ORDER, HERO_NAMES
from ..engine import MacEngine


LogFn = Callable[[str], None]

# 以金币招募按钮为主判定（原版 zmui/ok 过小，网页上易误报）
RECRUIT_BTN = (("jb100", 0.72), ("jb90", 0.72), ("jb0", 0.72))
RECRUIT_UI_HINT = ("cgzm", "zm")  # 仅作辅助，不再单独认定「在招募页」
DIAMOND_MARKS = ("zs", "zs_top", "jb100_h")  # 钻石相关
RESULT_OK = ("ok", "ok2", "zhe", "back", "cxjr")
ENTER_TEMPLATES = ("jinru",)  # 用户/自采：活动页「进入」


class CardModel:
    def __init__(
        self,
        engine: MacEngine,
        config: dict,
        log: LogFn,
        on_result: Optional[Callable[[dict], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.engine = engine
        self.config = config
        self.log = log
        self.on_result = on_result or (lambda *_: None)
        self.should_stop = should_stop or (lambda: False)
        self.total_count = 0
        self.total_cost = 0
        self.color_stats = {c: 0 for c in COLOR_ORDER}
        self.hero_stats = {h: 0 for h in HERO_NAMES}
        self.red_hits = 0
        self._same_color_streak = 0
        self._last_color_sig = ""
        self._no_result_streak = 0
        self._threshold_floor = 0.62

    def _stop(self) -> bool:
        return self.should_stop()

    def _sleep(self, sec: float) -> None:
        end = time.time() + sec
        while time.time() < end:
            if self._stop():
                return
            time.sleep(min(0.1, end - time.time()))

    def _th(self, base: float | None = None) -> float:
        t = float(self.config.get("threshold", 0.82) if base is None else base)
        return max(self._threshold_floor, t)

    def ensure_window(self) -> bool:
        kws = self.config.get("window_title_keywords") or ["百炼英雄"]
        win = self.engine.find_window(kws)
        if not win:
            self.log("未找到游戏窗口，请先打开网页版/小程序并保持可见")
            return False
        self.log(f"已绑定窗口: [{win.owner}] {win.title or '(无标题)'} {win.width}x{win.height}")
        return True

    def detect_recruit_ui(self) -> bool:
        """必须看到金币招募按钮，才认为在可抽卡界面。"""
        for name, th in RECRUIT_BTN:
            if self.engine.ishas(name, threshold=self._th(th)):
                return True
        # 略降阈值再认一次按钮
        low = max(self._threshold_floor, self._th() - 0.12)
        for name, _ in RECRUIT_BTN:
            if self.engine.ishas(name, threshold=low):
                return True
        return False

    def try_dismiss_activity_enter(self) -> bool:
        """活动/关卡页上的「进入」——点掉后便于回到可操作界面。"""
        for name in ENTER_TEMPLATES:
            if self.engine.load_template(name) is None:
                continue
            hit = self.engine.find_pic_ex(name, threshold=0.70)
            if hit and hit.score >= 0.70:
                self.log(f"检测到活动/关卡「进入」按钮 ({name}={hit.score:.2f})，尝试点击")
                if self.engine.click(hit.x, hit.y):
                    self._sleep(1.2)
                    return True
        return False

    def click_recruit_button(self) -> bool:
        for name, th in RECRUIT_BTN:
            if self.engine.click_pic(name, threshold=self._th(th)):
                self.log(f"点击招募按钮模板: {name}")
                return True
        self.log("未识别到金币招募按钮，尝试降低识别精度")
        low = max(self._threshold_floor, self._th() - 0.12)
        for name, _ in RECRUIT_BTN:
            if self.engine.click_pic(name, threshold=low):
                self.log(f"低精度点击: {name} th={low:.2f}")
                return True
        return False

    def detect_colors(self) -> list[str]:
        found = []
        th = self._th(0.78)
        for color in COLOR_ORDER:
            hits = self.engine.find_pic_all(f"color/{color}", threshold=th)
            if hits:
                found.extend([color] * len(hits))
                self.color_stats[color] += len(hits)
        return found

    def detect_heroes(self) -> list[str]:
        enabled = set(self.config.get("cards", {}).get("enabled_heroes") or HERO_NAMES.keys())
        found = []
        th = self._th(0.80)
        for key in enabled:
            hit = self.engine.find_pic(f"hero/{key}", threshold=th)
            if hit:
                found.append(key)
                self.hero_stats[key] = self.hero_stats.get(key, 0) + 1
        return found

    def check_bd_hong(self) -> bool:
        """保底红：幸运值满且为红时停止。"""
        th = self._th(0.8)
        if self.engine.ishas("jb100_h", threshold=th) or self.engine.ishas("hongqi", threshold=th):
            return True
        # 原版还有 baodi.png（若用户后续补模板）
        if self.engine.load_template("baodi") is not None and self.engine.ishas("baodi", threshold=th):
            return True
        return False

    def diamond_risk(self) -> bool:
        """识别疑似钻石消耗/钻石按钮（保守停机）。"""
        th = self._th(0.82)
        # 同时看到钻石图标且金币招募按钮消失时更危险
        has_zs = any(self.engine.ishas(n, threshold=th) for n in DIAMOND_MARKS)
        has_coin_btn = any(self.engine.ishas(n, threshold=self._th(0.75)) for n in ("jb0", "jb90", "jb100"))
        if has_zs and not has_coin_btn:
            return True
        return False

    def dismiss_result(self) -> None:
        for name in RESULT_OK:
            if self.engine.click_pic(name, threshold=self._th(0.75)):
                self._sleep(0.3)
                return
        win = self.engine.bind_window
        if win:
            self.engine.click(win.width // 2, int(win.height * 0.82))

    def _update_same_color_guard(self, colors: list[str]) -> bool:
        """多次英雄颜色相同 → 疑似网络卡顿，停机防耗钻。"""
        sig = ",".join(colors) if colors else ""
        if sig and sig == self._last_color_sig:
            self._same_color_streak += 1
        else:
            self._same_color_streak = 0
            self._last_color_sig = sig
        if self._same_color_streak >= 4:
            self.log("多次英雄颜色相同，疑似网络卡顿，为避免消耗钻石，程序退出")
            return True
        return False

    def run_once(self) -> bool:
        cards_cfg = self.config.get("cards", {})
        if cards_cfg.get("bd_h_stop") and self.check_bd_hong():
            self.log("检测到保底红/幸运值红满，停止抽卡")
            return False

        if self.diamond_risk():
            self.log("识别到钻石被消耗/钻石按钮风险，再次确认…")
            self._sleep(0.5)
            if self.diamond_risk():
                self.log("确认钻石风险，为避免消耗钻石，脚本停止运行")
                return False

        if not self.detect_recruit_ui():
            # 先尝试关掉结果弹层 / 活动进入页
            dismissed = False
            for name in RESULT_OK:
                if self.engine.click_pic(name, threshold=self._th(0.75)):
                    self.log(f"点击关闭/确认: {name}")
                    self._sleep(0.5)
                    dismissed = True
                    break
            if not dismissed and self.try_dismiss_activity_enter():
                dismissed = True
            if dismissed:
                return True
            self._no_result_streak += 1
            if self._no_result_streak in (1, 4, 8):
                self.log(
                    "未检测到金币招募按钮。请确认：已登录 → 离开活动页 → 打开「招募」界面。"
                    " 校准页可「招募链路自检」或框选 jb100 保存用户模板。"
                )
            if self._no_result_streak >= 15:
                self.log("多次未进入招募界面，已停止（避免空转误点）")
                return False
            self._sleep(1.0)
            return True
        else:
            self._no_result_streak = 0

        if cards_cfg.get("triple"):
            self.log("三倍模式：不区分英雄颜色分支（简化），仅点招募")

        if not self.click_recruit_button():
            self.log("未识别到招募按钮，稍后重试")
            self._sleep(1.0)
            return True

        self._sleep(0.8 if not cards_cfg.get("fast_zm") else 0.35)

        deadline = time.time() + (4 if cards_cfg.get("fast_zm") else 6)
        colors: list[str] = []
        heroes: list[str] = []
        while time.time() < deadline and not self._stop():
            if not cards_cfg.get("triple"):
                colors = self.detect_colors()
                heroes = self.detect_heroes()
            else:
                # 三倍：只等结果确认
                colors = self.detect_colors()
            if colors or heroes or any(self.engine.ishas(n, threshold=0.7) for n in ("ok", "ok2")):
                break
            self._sleep(0.25)

        if not colors and not heroes:
            self._no_result_streak += 1
            self.log("未检测到招募结果")
            if self._no_result_streak >= 6:
                self.log("多次未识别到招募结果，不再等待；本次不记录结果")
                self.dismiss_result()
                return True
        else:
            self._no_result_streak = 0

        self.total_count += 1
        self.total_cost += 1

        color_text = ",".join(COLOR_CN.get(c, c) for c in colors) or "未识别"
        hero_text = ",".join(HERO_NAMES.get(h, h) for h in heroes) or "未识别"
        self.log(f"第{self.total_count}次 颜色[{color_text}] 英雄[{hero_text}]")

        if self._update_same_color_guard(colors):
            self.on_result(self.snapshot())
            return False

        if "red" in colors:
            self.red_hits += 1
            self.log(f"发现红色英雄（累计红 {self.red_hits}）")
            if cards_cfg.get("h_stop") and self.red_hits >= int(cards_cfg.get("h_stop_num") or 1):
                self.log("达到遇红停止次数")
                self.on_result(self.snapshot())
                self.dismiss_result()
                return False

        self.on_result(self.snapshot())
        self.dismiss_result()
        self._sleep(float(self.config.get("loop_delay", 0.25)))

        limit = int(cards_cfg.get("cards_count") or 0)
        if limit > 0 and self.total_count >= limit:
            self.log(f"已达抽卡次数上限 {limit}")
            return False
        return True

    def snapshot(self) -> dict:
        return {
            "total_count": self.total_count,
            "total_cost": self.total_cost,
            "color_stats": dict(self.color_stats),
            "hero_stats": dict(self.hero_stats),
            "red_hits": self.red_hits,
        }

    def run_cards(self) -> None:
        self.log("开始抽卡")
        if not self.ensure_window():
            return
        fast = bool(self.config.get("cards", {}).get("fast_zm"))
        if fast:
            self.log("快速抽卡模式：检测较简，可能不稳定")
        if self.config.get("cards", {}).get("triple"):
            self.log("注意：此模式偏三倍逻辑，检测机制较少")
        while not self._stop():
            try:
                # 窗口丢失
                if self.engine.refresh_bind() is None and self.engine.bind_window is not None:
                    if not self.ensure_window():
                        self.log("游戏窗口关闭")
                        break
                cont = self.run_once()
                if not cont:
                    break
                if fast:
                    self._sleep(0.12)
            except Exception as e:
                self.log(f"抽卡程序异常: {e}")
                self.log("请检查错误日志 / debug 截图")
                break
        self.log("招募已完成 / 抽卡停止")
