"""Tkinter 主界面（对齐原版 view.App 选项卡结构）。"""

from __future__ import annotations

import queue
import threading
import time
import webbrowser
from typing import Optional

import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from ..config import (
    APP_TITLE,
    COLOR_CN,
    HERO_NAMES,
    ConfigStore,
    assets_dir,
    project_root,
    user_templates_dir,
)
from ..engine import MacEngine
from ..models import CardModel, CoinModel, SysModel
from .calibrate import CalibratePanel
from .recorder import RecorderPanel


class App:
    def __init__(self, root: tk.Tk, version: str) -> None:
        self.root = root
        self.version = version
        self.store = ConfigStore()
        self.cfg = self.store.get()
        self.engine = MacEngine(
            assets=assets_dir(),
            user_assets=user_templates_dir(),
            threshold=float(self.cfg.get("threshold", 0.82)),
            click_delay=float(self.cfg.get("click_delay", 0.08)),
            debug_dir=project_root() / "debug",
        )
        self._stop_flag = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._queue: queue.Queue = queue.Queue()
        self._running = False
        self._timer_start = 0.0

        self.root.title(APP_TITLE)
        self.root.geometry("980x720")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        self._build_ui()
        self._load_to_ui()
        self.log(f"程序启动 {self.version}（Mac 重写版，无卡密服务器）")
        self.log("使用前请授予：辅助功能 + 屏幕录制 权限")
        self.log("建议先到「校准」页绑定窗口 → 截图 → 招募链路自检 / 框选用户模板")
        self.log(f"用户模板目录: {user_templates_dir()}")
        self.root.after(200, self._poll_queue)

    # ---------- UI ----------
    def _build_ui(self) -> None:
        top = ttk.Frame(self.root)
        top.pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(top, text=APP_TITLE).pack(side=tk.LEFT)
        self.lbl_timer = ttk.Label(top, text="已运行 00:00:00")
        self.lbl_timer.pack(side=tk.RIGHT)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        self.tab_card = ttk.Frame(self.notebook)
        self.tab_coin = ttk.Frame(self.notebook)
        self.tab_sys = ttk.Frame(self.notebook)
        self.tab_cal = ttk.Frame(self.notebook)
        self.tab_rec = ttk.Frame(self.notebook)
        self.tab_qa = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_card, text="抽卡")
        self.notebook.add(self.tab_coin, text="金币")
        self.notebook.add(self.tab_sys, text="系统/竞技场")
        self.notebook.add(self.tab_cal, text="校准")
        self.notebook.add(self.tab_rec, text="录制")
        self.notebook.add(self.tab_qa, text="常见问题")

        self._build_card_tab()
        self._build_coin_tab()
        self._build_sys_tab()
        self._build_cal_tab()
        self._build_rec_tab()
        self._build_qa_tab()

        bottom = ttk.Frame(self.root)
        bottom.pack(fill=tk.X, padx=8, pady=6)
        self.btn_start = ttk.Button(bottom, text="开始", command=self.start_action)
        self.btn_stop = ttk.Button(bottom, text="停止", command=self.stop_action, state=tk.DISABLED)
        self.btn_bind = ttk.Button(bottom, text="绑定窗口", command=self.bind_window)
        self.btn_save = ttk.Button(bottom, text="保存配置", command=self.save_config)
        self.btn_open = ttk.Button(bottom, text="打开游戏页", command=self.open_web)
        self.btn_debug = ttk.Button(bottom, text="导出调试图", command=self.export_debug)
        for b in (self.btn_start, self.btn_stop, self.btn_bind, self.btn_save, self.btn_open, self.btn_debug):
            b.pack(side=tk.LEFT, padx=4)

        self.txt_log = scrolledtext.ScrolledText(self.root, height=12, font=("Menlo", 11))
        self.txt_log.pack(fill=tk.BOTH, expand=False, padx=8, pady=(0, 8))

    def _build_card_tab(self) -> None:
        f = self.tab_card
        row1 = ttk.Frame(f)
        row1.pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(row1, text="抽卡次数(0=无限)").pack(side=tk.LEFT)
        self.var_cards_count = tk.StringVar(value="0")
        ttk.Entry(row1, textvariable=self.var_cards_count, width=8).pack(side=tk.LEFT, padx=6)

        self.var_fast_zm = tk.BooleanVar(value=False)
        self.var_bd_h_stop = tk.BooleanVar(value=True)
        self.var_h_stop = tk.BooleanVar(value=False)
        self.var_triple = tk.BooleanVar(value=False)
        ttk.Checkbutton(row1, text="快速抽卡", variable=self.var_fast_zm).pack(side=tk.LEFT, padx=6)
        ttk.Checkbutton(row1, text="保底红停止", variable=self.var_bd_h_stop).pack(side=tk.LEFT, padx=6)
        ttk.Checkbutton(row1, text="遇红停止", variable=self.var_h_stop).pack(side=tk.LEFT, padx=6)
        ttk.Checkbutton(row1, text="三倍模式(提示)", variable=self.var_triple).pack(side=tk.LEFT, padx=6)

        row2 = ttk.Frame(f)
        row2.pack(fill=tk.X, padx=8, pady=4)
        ttk.Label(row2, text="遇红停止数").pack(side=tk.LEFT)
        self.var_h_stop_num = tk.StringVar(value="1")
        ttk.Entry(row2, textvariable=self.var_h_stop_num, width=6).pack(side=tk.LEFT, padx=6)
        ttk.Label(row2, text="匹配阈值").pack(side=tk.LEFT, padx=(12, 0))
        self.var_threshold = tk.StringVar(value="0.82")
        ttk.Entry(row2, textvariable=self.var_threshold, width=6).pack(side=tk.LEFT, padx=6)

        hero_frame = ttk.LabelFrame(f, text="关注英雄（结果统计用）")
        hero_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)
        self.hero_vars: dict[str, tk.BooleanVar] = {}
        r = c = 0
        for key, name in HERO_NAMES.items():
            var = tk.BooleanVar(value=True)
            self.hero_vars[key] = var
            ttk.Checkbutton(hero_frame, text=name, variable=var).grid(row=r, column=c, sticky=tk.W, padx=4, pady=2)
            c += 1
            if c >= 6:
                c = 0
                r += 1

        self.lbl_card_res = ttk.Label(f, text="抽卡结果: 总次数0 / 总消耗0")
        self.lbl_card_res.pack(anchor=tk.W, padx=8, pady=4)

    def _build_coin_tab(self) -> None:
        f = self.tab_coin
        row = ttk.Frame(f)
        row.pack(fill=tk.X, padx=8, pady=6)
        self.var_coins_mode = tk.StringVar(value="default")
        ttk.Radiobutton(row, text="默认模式", value="default", variable=self.var_coins_mode).pack(side=tk.LEFT)
        ttk.Radiobutton(row, text="自定义刷图", value="custom", variable=self.var_coins_mode).pack(side=tk.LEFT, padx=8)

        boss_frame = ttk.LabelFrame(f, text="默认 BOSS")
        boss_frame.pack(fill=tk.X, padx=8, pady=4)
        self.boss_vars = {}
        for i, name in enumerate(["疯牛魔王", "树精长老", "剧毒蝎王", "树精领主", "火焰石像"]):
            var = tk.BooleanVar(value=(i == 0))
            self.boss_vars[name] = var
            ttk.Checkbutton(boss_frame, text=name, variable=var).pack(side=tk.LEFT, padx=6)

        time_row = ttk.Frame(f)
        time_row.pack(fill=tk.X, padx=8, pady=4)
        self.var_start_min = tk.StringVar(value="0")
        self.var_end_min = tk.StringVar(value="0")
        self.var_restart_min = tk.StringVar(value="0")
        for label, var in (
            ("开始(分钟,0立即)", self.var_start_min),
            ("结束(0不停止)", self.var_end_min),
            ("重启间隔(0不重启)", self.var_restart_min),
        ):
            ttk.Label(time_row, text=label).pack(side=tk.LEFT)
            ttk.Entry(time_row, textvariable=var, width=6).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(f, text="自定义脚本").pack(anchor=tk.W, padx=8)
        self.txt_script = scrolledtext.ScrolledText(f, height=12, font=("Menlo", 11))
        self.txt_script.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

    def _build_sys_tab(self) -> None:
        f = self.tab_sys
        row = ttk.Frame(f)
        row.pack(fill=tk.X, padx=8, pady=8)
        ttk.Label(row, text="竞技场场次").pack(side=tk.LEFT)
        self.var_jjc_count = tk.StringVar(value="10")
        ttk.Entry(row, textvariable=self.var_jjc_count, width=8).pack(side=tk.LEFT, padx=6)
        self.var_random_btn = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="随机点击偏移", variable=self.var_random_btn).pack(side=tk.LEFT, padx=8)

        kw_row = ttk.Frame(f)
        kw_row.pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(kw_row, text="窗口标题关键字(|分隔)").pack(side=tk.LEFT)
        self.var_keywords = tk.StringVar(value="百炼英雄|微信|WeChat|Chrome|Safari")
        ttk.Entry(kw_row, textvariable=self.var_keywords, width=50).pack(side=tk.LEFT, padx=6)

        url_row = ttk.Frame(f)
        url_row.pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(url_row, text="游戏网址").pack(side=tk.LEFT)
        self.var_game_url = tk.StringVar(value="")
        ttk.Entry(url_row, textvariable=self.var_game_url, width=60).pack(side=tk.LEFT, padx=6)

        tip = (
            "Mac 版说明：\n"
            "1. 用浏览器打开游戏 H5/网页版，窗口不要被遮挡。\n"
            "2. 系统设置 → 隐私与安全性 → 屏幕录制 / 辅助功能，勾选终端或 Python。\n"
            "3. 点「绑定窗口」确认截到的是游戏窗。\n"
            "4. 模板图来自原版 images，分辨率/缩放不一致时请调低匹配阈值。\n"
            "5. 本移植不连接原作者卡密服务器，本地直接可用。"
        )
        ttk.Label(f, text=tip, justify=tk.LEFT).pack(anchor=tk.W, padx=8, pady=12)

    def _build_cal_tab(self) -> None:
        self.cal_panel = CalibratePanel(
            self.tab_cal,
            engine=self.engine,
            get_keywords=lambda: [x.strip() for x in self.var_keywords.get().split("|") if x.strip()],
            log=self.log,
            on_threshold=self._apply_threshold_from_cal,
        )
        self.cal_panel.pack(fill=tk.BOTH, expand=True)

    def _apply_threshold_from_cal(self, value: float) -> None:
        self.var_threshold.set(f"{float(value):.3f}")
        self.engine.threshold = float(value)
        self.cfg["threshold"] = float(value)

    def _build_rec_tab(self) -> None:
        self.rec_panel = RecorderPanel(
            self.tab_rec,
            engine=self.engine,
            log=self.log,
            apply_script=self._apply_recorded_script,
        )
        self.rec_panel.pack(fill=tk.BOTH, expand=True)

    def _apply_recorded_script(self, text: str) -> None:
        self.notebook.select(self.tab_coin)
        self.var_coins_mode.set("custom")
        self.txt_script.delete("1.0", tk.END)
        self.txt_script.insert(tk.END, text)
        self.log("已把录制脚本写入「金币 → 自定义刷图」")

    def export_debug(self) -> None:
        path = project_root() / "debug" / f"manual_{int(time.time())}.png"
        out = self.engine.save_capture(path, annotated=True)
        if out:
            self.log(f"调试图: {out}")
            messagebox.showinfo("提示", f"已保存\n{out}")
        else:
            messagebox.showwarning("提示", "请先绑定窗口并截图/探测模板")

    def _build_qa_tab(self) -> None:
        txt = scrolledtext.ScrolledText(self.tab_qa, font=("PingFang SC", 12))
        txt.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        txt.insert(
            tk.END,
            "Q: 提示未找到游戏窗口？\n"
            "A: 把浏览器/小程序窗口置于前台，标题尽量包含“百炼英雄”，或在系统页改关键字。\n\n"
            "Q: 点了开始没反应？\n"
            "A: 检查辅助功能与屏幕录制权限；macOS 权限变更后需重启本程序。\n\n"
            "Q: 识别不准？\n"
            "A: 原模板来自 Windows。Mac 上优先：校准页框选真实按钮保存为用户模板（user_templates/），\n"
            "   再跑「招募链路自检」。引擎已做 Retina 坐标换算 + 多尺度匹配。\n\n"
            "Q: 和原版 exe 的关系？\n"
            "A: 本项目按逆向结构重写，替换了傲甲 DLL 与 Win32 API，不保证 1:1 行为一致。\n\n"
            "Q: 怎么校准？\n"
            "A: 打开游戏 →「校准」绑定窗口 → 截图 →「招募链路自检」。\n"
            "   缺按钮时在预览拖拽框选 → 命名 jb100 等 → 保存用户模板 → 建议阈值。\n\n"
            "Q: 怎么录制自定义脚本？\n"
            "A:「录制」页开始后，用方向键移动并松手结算；可插入等待/点击/开宝箱等指令。\n",
        )
        txt.configure(state=tk.DISABLED)

    # ---------- config bind ----------
    def _load_to_ui(self) -> None:
        c = self.cfg
        self.var_cards_count.set(str(c["cards"]["cards_count"]))
        self.var_fast_zm.set(bool(c["cards"]["fast_zm"]))
        self.var_bd_h_stop.set(bool(c["cards"]["bd_h_stop"]))
        self.var_h_stop.set(bool(c["cards"]["h_stop"]))
        self.var_h_stop_num.set(str(c["cards"]["h_stop_num"]))
        self.var_triple.set(bool(c["cards"].get("triple", False)))
        self.var_threshold.set(str(c.get("threshold", 0.82)))
        enabled = set(c["cards"].get("enabled_heroes") or [])
        for k, var in self.hero_vars.items():
            var.set(k in enabled if enabled else True)

        self.var_coins_mode.set(c["coins"].get("mode", "default"))
        selected = set(c["coins"].get("selected_bosses") or [])
        for name, var in self.boss_vars.items():
            var.set(name in selected)
        self.var_start_min.set(str(c["coins"].get("start_min", 0)))
        self.var_end_min.set(str(c["coins"].get("end_min", 0)))
        self.var_restart_min.set(str(c["coins"].get("restart_min", 0)))
        self.txt_script.delete("1.0", tk.END)
        self.txt_script.insert(tk.END, c["coins"].get("custom_script") or "")

        self.var_jjc_count.set(str(c["sys"].get("jjc_count", 10)))
        self.var_random_btn.set(bool(c["sys"].get("random_btn", True)))
        self.var_keywords.set("|".join(c.get("window_title_keywords") or []))
        self.var_game_url.set(c.get("game_url") or "")

    def _ui_to_cfg(self) -> None:
        self.cfg["threshold"] = float(self.var_threshold.get() or 0.82)
        self.cfg["window_title_keywords"] = [x.strip() for x in self.var_keywords.get().split("|") if x.strip()]
        self.cfg["game_url"] = self.var_game_url.get().strip()
        self.cfg["cards"]["cards_count"] = int(self.var_cards_count.get() or 0)
        self.cfg["cards"]["fast_zm"] = bool(self.var_fast_zm.get())
        self.cfg["cards"]["bd_h_stop"] = bool(self.var_bd_h_stop.get())
        self.cfg["cards"]["h_stop"] = bool(self.var_h_stop.get())
        self.cfg["cards"]["h_stop_num"] = int(self.var_h_stop_num.get() or 1)
        self.cfg["cards"]["triple"] = bool(self.var_triple.get())
        self.cfg["cards"]["enabled_heroes"] = [k for k, v in self.hero_vars.items() if v.get()]
        self.cfg["coins"]["mode"] = self.var_coins_mode.get()
        self.cfg["coins"]["selected_bosses"] = [k for k, v in self.boss_vars.items() if v.get()]
        self.cfg["coins"]["start_min"] = int(self.var_start_min.get() or 0)
        self.cfg["coins"]["end_min"] = int(self.var_end_min.get() or 0)
        self.cfg["coins"]["restart_min"] = int(self.var_restart_min.get() or 0)
        self.cfg["coins"]["custom_script"] = self.txt_script.get("1.0", tk.END)
        self.cfg["sys"]["jjc_count"] = int(self.var_jjc_count.get() or 10)
        self.cfg["sys"]["random_btn"] = bool(self.var_random_btn.get())
        self.engine.threshold = float(self.cfg["threshold"])

    def save_config(self) -> None:
        try:
            self._ui_to_cfg()
            self.store.data = self.cfg
            self.store.save()
            self.log("保存成功")
            messagebox.showinfo("提示", "保存成功")
        except Exception as e:
            messagebox.showerror("错误", f"保存配置失败: {e}")

    # ---------- runtime ----------
    def log(self, msg: str) -> None:
        self._queue.put(("log", msg))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "log":
                    ts = time.strftime("%H:%M:%S")
                    self.txt_log.insert(tk.END, f"[{ts}] {payload}\n")
                    self.txt_log.see(tk.END)
                elif kind == "card_res":
                    colors = ", ".join(f"{COLOR_CN.get(k,k)}:{v}" for k, v in payload.get("color_stats", {}).items() if v)
                    self.lbl_card_res.configure(
                        text=f"抽卡结果: 总次数{payload.get('total_count',0)} / 总消耗{payload.get('total_cost',0)} / {colors}"
                    )
                elif kind == "state":
                    running = bool(payload)
                    self._running = running
                    self.btn_start.configure(state=tk.DISABLED if running else tk.NORMAL)
                    self.btn_stop.configure(state=tk.NORMAL if running else tk.DISABLED)
        except queue.Empty:
            pass
        if self._running:
            elapsed = int(time.time() - self._timer_start)
            h, rem = divmod(elapsed, 3600)
            m, s = divmod(rem, 60)
            self.lbl_timer.configure(text=f"已运行 {h:02d}:{m:02d}:{s:02d}")
        self.root.after(200, self._poll_queue)

    def bind_window(self) -> None:
        self._ui_to_cfg()
        win = self.engine.find_window(self.cfg.get("window_title_keywords") or ["百炼英雄"])
        if not win:
            # 列出候选方便排查
            wins = self.engine.list_windows()[:15]
            detail = "\n".join(f"- [{w.owner}] {w.title or '(无标题)'} {w.width}x{w.height}" for w in wins) or "(无窗口)"
            self.log("未找到匹配窗口，当前可见窗口示例：")
            self.log(detail)
            messagebox.showwarning("提示", "未找到游戏窗口，请看日志中的窗口列表并调整关键字")
            return
        self.log(f"绑定成功: [{win.owner}] {win.title or '(无标题)'} @({win.x},{win.y}) {win.width}x{win.height}")
        bundle = self.engine.capture_bundle()
        if bundle is None:
            messagebox.showerror("错误", f"截图失败，请检查屏幕录制权限\n{self.engine.last_error}")
        else:
            self.log(
                f"截图 OK scale={bundle.scale:.2f} px={bundle.pixel_w}x{bundle.pixel_h} "
                f"points={bundle.point_w:.0f}x{bundle.point_h:.0f}"
            )
            messagebox.showinfo(
                "提示",
                f"绑定成功\n像素 {bundle.pixel_w}x{bundle.pixel_h}\n"
                f"逻辑点 {bundle.point_w:.0f}x{bundle.point_h:.0f}\n"
                f"scale={bundle.scale:.2f}\n\n建议到「校准」页跑「招募链路自检」",
            )

    def open_web(self) -> None:
        url = self.var_game_url.get().strip() or self.cfg.get("game_url")
        if not url:
            messagebox.showwarning("提示", "请先填写游戏网址")
            return
        webbrowser.open(url)
        self.log(f"打开网页: {url}")

    def start_action(self) -> None:
        if self._running:
            return
        try:
            self._ui_to_cfg()
        except Exception as e:
            messagebox.showerror("错误", f"配置有误: {e}")
            return
        if not self.engine.bind_window:
            if not self.engine.find_window(self.cfg.get("window_title_keywords") or []):
                messagebox.showwarning("提示", "请先绑定游戏窗口")
                return
        self._stop_flag.clear()
        self._timer_start = time.time()
        tab = self.notebook.index(self.notebook.select())
        self._queue.put(("state", True))
        self._worker = threading.Thread(target=self._run_worker, args=(tab,), daemon=True)
        self._worker.start()

    def stop_action(self) -> None:
        self._stop_flag.set()
        self.log("停止脚本")

    def _run_worker(self, tab_index: int) -> None:
        try:
            if tab_index == 0:
                model = CardModel(
                    self.engine,
                    self.cfg,
                    log=self.log,
                    on_result=lambda d: self._queue.put(("card_res", d)),
                    should_stop=self._stop_flag.is_set,
                )
                model.run_cards()
            elif tab_index == 1:
                model = CoinModel(
                    self.engine,
                    self.cfg,
                    log=self.log,
                    should_stop=self._stop_flag.is_set,
                )
                model.run_coins()
            elif tab_index == 2:
                model = SysModel(
                    self.engine,
                    self.cfg,
                    log=self.log,
                    should_stop=self._stop_flag.is_set,
                )
                model.run_sys_model()
            else:
                self.log("请切换到「抽卡 / 金币 / 系统」页再点开始（校准/录制页不跑脚本）")
        finally:
            self._queue.put(("state", False))

    def on_closing(self) -> None:
        self._stop_flag.set()
        try:
            self._ui_to_cfg()
            self.store.data = self.cfg
            self.store.save()
        except Exception:
            pass
        self.root.destroy()
