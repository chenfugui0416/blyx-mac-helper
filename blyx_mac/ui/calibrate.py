"""校准工具 v2：窗口绑定、Retina 安全预览、框选存模板、阈值建议、招募链路自检。"""

from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from typing import Callable, Optional

from PIL import Image, ImageTk

from ..config import project_root
from ..engine import MacEngine
from ..engine.mac_engine import MatchResult


COMMON_TEMPLATES = [
    "zm",
    "zmui1",
    "zmui2",
    "cgzm",
    "jb0",
    "jb90",
    "jb100",
    "jb100_h",
    "ok",
    "ok2",
    "zhe",
    "back",
    "hongqi",
    "zs",
    "zs_top",
    "color/red",
    "color/golden",
    "color/purple",
    "color/blue",
    "color/white",
    "baoxiang",
    "bx",
    "lingqu",
    "jjcui",
    "jjcvs",
    "jjcfanhui",
    "web_login",
]


class CalibratePanel(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        engine: MacEngine,
        get_keywords: Callable[[], list[str]],
        log: Callable[[str], None],
        on_threshold: Optional[Callable[[float], None]] = None,
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        self.engine = engine
        self.get_keywords = get_keywords
        self.log = log
        self.on_threshold = on_threshold
        self._photo: Optional[ImageTk.PhotoImage] = None
        self._preview_img = None  # PIL 显示图
        self._display_scale = 1.0  # 预览相对「像素截图」的缩放
        self._wins: list = []
        self._sel_start: Optional[tuple[int, int]] = None  # canvas 像素
        self._sel_rect_id: Optional[int] = None
        self._crop_box_px: Optional[tuple[int, int, int, int]] = None  # 截图像素坐标
        self._build()

    def _build(self) -> None:
        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=6, pady=4)
        for text, cmd in (
            ("刷新窗口列表", self.refresh_windows),
            ("按关键字绑定", self.bind_by_keywords),
            ("截图预览", self.capture_preview),
            ("保存截图", self.save_capture),
            ("保存标注图", self.save_annotated),
            ("引擎诊断", self.show_diagnostics),
        ):
            ttk.Button(top, text=text, command=cmd).pack(side=tk.LEFT, padx=2)

        mid = ttk.Frame(self)
        mid.pack(fill=tk.X, padx=6, pady=4)
        ttk.Label(mid, text="窗口").pack(side=tk.LEFT)
        self.cmb_win = ttk.Combobox(mid, width=70, state="readonly")
        self.cmb_win.pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)
        ttk.Button(mid, text="绑定所选", command=self.bind_selected).pack(side=tk.LEFT, padx=2)

        row = ttk.Frame(self)
        row.pack(fill=tk.X, padx=6, pady=4)
        ttk.Label(row, text="模板").pack(side=tk.LEFT)
        self.cmb_tpl = ttk.Combobox(row, width=28, values=self.engine.list_templates())
        self.cmb_tpl.pack(side=tk.LEFT, padx=4)
        if self.cmb_tpl["values"]:
            self.cmb_tpl.current(0)
        ttk.Label(row, text="探测阈值").pack(side=tk.LEFT)
        self.var_th = tk.StringVar(value="0.45")
        ttk.Entry(row, textvariable=self.var_th, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Button(row, text="测当前", command=self.probe_one).pack(side=tk.LEFT, padx=2)
        ttk.Button(row, text="测常用", command=self.probe_common).pack(side=tk.LEFT, padx=2)
        ttk.Button(row, text="测全部", command=self.probe_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(row, text="建议阈值", command=self.suggest_threshold).pack(side=tk.LEFT, padx=2)
        ttk.Button(row, text="招募链路自检", command=self.pipeline_check).pack(side=tk.LEFT, padx=2)

        crop_row = ttk.Frame(self)
        crop_row.pack(fill=tk.X, padx=6, pady=2)
        ttk.Label(crop_row, text="框选模板名").pack(side=tk.LEFT)
        self.var_crop_name = tk.StringVar(value="jb100")
        ttk.Entry(crop_row, textvariable=self.var_crop_name, width=18).pack(side=tk.LEFT, padx=4)
        ttk.Button(crop_row, text="保存框选为用户模板", command=self.save_crop_template).pack(side=tk.LEFT, padx=2)
        ttk.Button(crop_row, text="打开用户模板目录", command=self.open_user_dir).pack(side=tk.LEFT, padx=2)
        ttk.Button(crop_row, text="刷新模板列表", command=self.refresh_templates).pack(side=tk.LEFT, padx=2)
        ttk.Label(
            crop_row,
            text="在预览上拖拽框选；模板优先用 user_templates/",
        ).pack(side=tk.LEFT, padx=8)

        self.lbl_info = ttk.Label(
            self,
            text="单击取色；拖拽框选区域。匹配标注用像素坐标（Retina 安全）。",
        )
        self.lbl_info.pack(anchor=tk.W, padx=8, pady=2)

        body = ttk.Frame(self)
        body.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

        left = ttk.Frame(body)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(left, bg="#222", height=360)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self.on_canvas_press)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)

        right = ttk.Frame(body, width=300)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        ttk.Label(right, text="匹配 / 自检结果（高→低）").pack(anchor=tk.W)
        self.lst = tk.Listbox(right, width=42, height=18, font=("Menlo", 11))
        self.lst.pack(fill=tk.BOTH, expand=True)
        self.lst.bind("<<ListboxSelect>>", self.on_select_match)
        ttk.Button(right, text="点击选中匹配点", command=self.click_selected).pack(fill=tk.X, pady=4)
        ttk.Button(right, text="应用建议阈值到业务", command=self.apply_best_suggest).pack(fill=tk.X, pady=2)

        self._last_suggest: Optional[float] = None

    # ---------- window / capture ----------
    def refresh_windows(self) -> None:
        self._wins = self.engine.list_windows()
        labels = [f"{w.window_id}: {w.label()}" for w in self._wins]
        self.cmb_win["values"] = labels
        if labels:
            self.cmb_win.current(0)
        self.log(f"窗口列表 {len(labels)} 个")

    def bind_selected(self) -> None:
        idx = self.cmb_win.current()
        if idx < 0 or idx >= len(self._wins):
            messagebox.showwarning("提示", "请先刷新并选择窗口")
            return
        win = self._wins[idx]
        self.engine.bind_window = win
        self.log(f"绑定: {win.label()}")
        self.capture_preview()

    def bind_by_keywords(self) -> None:
        win = self.engine.find_window(self.get_keywords())
        if not win:
            messagebox.showwarning("提示", "关键字未匹配到窗口，请用列表手动绑定")
            self.refresh_windows()
            return
        self.log(f"关键字绑定: {win.label()}")
        self.capture_preview()

    def capture_preview(self) -> None:
        bundle = self.engine.capture_bundle()
        if bundle is None:
            messagebox.showerror("错误", f"截图失败：{self.engine.last_error or '未绑定窗口或无屏幕录制权限'}")
            return
        self._show_bgr(bundle.bgr, self.engine.last_matches)
        d = self.engine.diagnostics()
        self.log(
            f"截图 OK scale={bundle.scale:.2f} px={bundle.pixel_w}x{bundle.pixel_h} "
            f"points≈{bundle.point_w:.0f}x{bundle.point_h:.0f} display={d.get('display_scale')}"
        )

    def _draw_matches_on(self, vis, matches: list[MatchResult]) -> None:
        import cv2

        for m in matches:
            px, py = m.px, m.py
            if (px == 0 and py == 0) and self.engine.last_bundle:
                px, py = self.engine.last_bundle.point_to_px(m.x, m.y)
            r = max(8, int(10 * (self.engine.last_bundle.scale if self.engine.last_bundle else 1)))
            cv2.circle(vis, (px, py), r, (0, 0, 255), 2)
            cv2.putText(
                vis,
                f"{Path(m.name).name}:{m.score:.2f}",
                (max(0, px - 20), max(16, py - 14)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45 * max(1.0, (self.engine.last_bundle.scale if self.engine.last_bundle else 1) / 2),
                (0, 255, 0),
                1,
                cv2.LINE_AA,
            )

    def _show_bgr(self, bgr, matches: list[MatchResult] | None = None) -> None:
        import cv2

        vis = bgr.copy()
        if matches:
            self._draw_matches_on(vis, matches)
        # 画当前框选
        if self._crop_box_px:
            x1, y1, x2, y2 = self._crop_box_px
            cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 255), 2)

        rgb = cv2.cvtColor(vis, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        self.canvas.update_idletasks()
        cw = max(200, self.canvas.winfo_width())
        ch = max(200, self.canvas.winfo_height())
        scale = min(cw / pil.width, ch / pil.height, 1.0)
        self._display_scale = scale
        if scale < 1.0:
            pil = pil.resize((int(pil.width * scale), int(pil.height * scale)), Image.Resampling.BILINEAR)
        self._preview_img = pil
        self._photo = ImageTk.PhotoImage(pil)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self._photo)
        self._sel_rect_id = None
        scale_info = ""
        if self.engine.last_bundle:
            scale_info = f" capture_scale={self.engine.last_bundle.scale:.2f}"
        self.lbl_info.configure(
            text=f"预览像素 {bgr.shape[1]}x{bgr.shape[0]} 显示缩放 {scale:.2f}{scale_info}"
        )

    def save_capture(self) -> None:
        path = project_root() / "debug" / f"capture_{time.strftime('%Y%m%d_%H%M%S')}.png"
        out = self.engine.save_capture(path, annotated=False)
        if out:
            self.log(f"已保存截图: {out}")
            messagebox.showinfo("提示", f"已保存\n{out}")
        else:
            messagebox.showerror("错误", "无截图可保存")

    def save_annotated(self) -> None:
        path = project_root() / "debug" / f"anno_{time.strftime('%Y%m%d_%H%M%S')}.png"
        out = self.engine.save_capture(path, annotated=True)
        if out:
            self.log(f"已保存标注图: {out}")
            messagebox.showinfo("提示", f"已保存\n{out}")
        else:
            messagebox.showerror("错误", "无截图可保存")

    def show_diagnostics(self) -> None:
        d = self.engine.diagnostics()
        lines = [f"{k}: {v}" for k, v in d.items()]
        text = "\n".join(lines)
        self.log("引擎诊断:\n" + text)
        messagebox.showinfo("引擎诊断", text)

    def refresh_templates(self) -> None:
        self.engine.clear_template_cache()
        names = self.engine.list_templates()
        self.cmb_tpl["values"] = names
        self.log(f"模板列表 {len(names)} 个（含用户模板 {self.engine.user_assets}）")

    def open_user_dir(self) -> None:
        path = self.engine.ensure_user_assets()
        try:
            import subprocess

            subprocess.run(["open", str(path)], check=False)
        except Exception:
            pass
        self.log(f"用户模板目录: {path}")

    # ---------- matching ----------
    def _th(self) -> float:
        try:
            return float(self.var_th.get())
        except Exception:
            return 0.45

    def _fill_list(self, hits: list[MatchResult]) -> None:
        self.lst.delete(0, tk.END)
        for h in hits:
            src = ""
            tp = self.engine.template_path(h.name)
            if tp and str(self.engine.user_assets) in str(tp):
                src = " [user]"
            self.lst.insert(
                tk.END,
                f"{h.score:.3f} s={h.scale:.2f} {h.method} ({h.x},{h.y}) {h.name}{src}",
            )
        if self.engine.last_capture is not None:
            self._show_bgr(self.engine.last_capture, hits)

    def probe_one(self) -> None:
        name = self.cmb_tpl.get().strip()
        if not name:
            return
        if not self.engine.bind_window:
            messagebox.showwarning("提示", "请先绑定窗口")
            return
        hit = self.engine.probe_template(name, threshold=self._th())
        if not hit:
            self.log(f"未匹配: {name}（err={self.engine.last_error}）")
            self._fill_list([])
            return
        sug = min(0.95, max(0.55, hit.score - 0.04))
        self._last_suggest = sug
        self.log(
            f"匹配 {name}: score={hit.score:.3f} scale={hit.scale:.2f} method={hit.method} "
            f"@点({hit.x},{hit.y}) px({hit.px},{hit.py}) 建议业务阈值≈{sug:.2f}"
        )
        self._fill_list([hit])

    def probe_common(self) -> None:
        self._probe_names(COMMON_TEMPLATES)

    def probe_all(self) -> None:
        self._probe_names(self.engine.list_templates())

    def _probe_names(self, names: list[str]) -> None:
        if not self.engine.bind_window:
            messagebox.showwarning("提示", "请先绑定窗口")
            return
        hits = self.engine.probe_many(names, threshold=self._th())
        self.log(f"探测完成: {len(hits)}/{len(names)} 个超过阈值 {self._th():.2f}")
        if hits:
            best = hits[0]
            self._last_suggest = min(0.95, max(0.55, best.score - 0.04))
            self.log(f"最高分 {best.name}={best.score:.3f} → 建议阈值≈{self._last_suggest:.2f}")
        self._fill_list(hits)

    def suggest_threshold(self) -> None:
        name = self.cmb_tpl.get().strip()
        if not name:
            messagebox.showwarning("提示", "请选择模板")
            return
        if not self.engine.bind_window:
            messagebox.showwarning("提示", "请先绑定窗口")
            return
        sug = self.engine.suggest_threshold(name)
        hit = self.engine.last_matches[0] if self.engine.last_matches else None
        if sug is None or hit is None:
            self.log(f"无法为 {name} 建议阈值（当前画面未命中）")
            messagebox.showwarning("提示", "当前画面未找到该模板，请先打开对应界面")
            return
        self._last_suggest = sug
        self.var_th.set(f"{max(0.30, sug - 0.15):.2f}")
        self.log(f"建议业务阈值 {name}: {sug:.3f}（探测分 {hit.score:.3f}）")
        if self.on_threshold:
            if messagebox.askyesno("建议阈值", f"{name} 建议业务阈值 {sug:.3f}\n是否写入抽卡页阈值？"):
                self.on_threshold(sug)
                self.log(f"已写入业务阈值 {sug:.3f}")
        self._fill_list([hit])

    def pipeline_check(self) -> None:
        if not self.engine.bind_window:
            messagebox.showwarning("提示", "请先绑定窗口")
            return
        report = self.engine.pipeline_check_recruit()
        self.lst.delete(0, tk.END)
        if not report.get("size"):
            self.log(f"链路自检失败: {report.get('error')}")
            messagebox.showerror("错误", report.get("error") or "截图失败")
            return
        scene = report.get("scene") or "unknown"
        hint = report.get("hint") or ""
        self.log(
            f"招募链路自检 scene={scene} scale={report.get('scale')} size={report.get('size')} "
            f"{'可用' if report.get('ok') else '不可用'}"
        )
        if hint:
            self.log(f"提示: {hint}")
        suggests = []
        for it in report.get("items") or []:
            if it.get("name"):
                line = (
                    f"{it['group']}: {it['name']}={it['score']:.3f} "
                    f"@ {it['xy']} th≈{it['suggest_th']} [{it.get('source')}]"
                )
                if it.get("suggest_th") and it["group"] == "金币按钮":
                    suggests.append(it["suggest_th"])
            else:
                line = f"{it['group']}: 未命中"
            self.lst.insert(tk.END, line)
            self.log(line)
        if suggests:
            self._last_suggest = min(suggests)
        if self.engine.last_capture is not None:
            self._show_bgr(self.engine.last_capture, self.engine.last_matches)
        if report.get("ok"):
            messagebox.showinfo("链路自检", f"{hint}\n阈值建议见列表。")
        else:
            messagebox.showwarning("链路自检", hint or "未识别到金币招募按钮")

    def apply_best_suggest(self) -> None:
        if self._last_suggest is None:
            messagebox.showwarning("提示", "请先测模板或跑链路自检")
            return
        if self.on_threshold:
            self.on_threshold(float(self._last_suggest))
            self.log(f"已应用业务阈值 {self._last_suggest:.3f}")
            messagebox.showinfo("提示", f"业务阈值已设为 {self._last_suggest:.3f}")
        else:
            messagebox.showinfo("提示", f"建议阈值 {self._last_suggest:.3f}（无回调，请手动填写）")

    def on_select_match(self, _evt=None) -> None:
        sel = self.lst.curselection()
        if not sel or not self.engine.last_matches:
            return
        idx = sel[0]
        if idx >= len(self.engine.last_matches):
            return
        m = self.engine.last_matches[idx]
        if self.engine.last_capture is not None:
            self._show_bgr(self.engine.last_capture, [m])

    def click_selected(self) -> None:
        sel = self.lst.curselection()
        if not sel or not self.engine.last_matches:
            messagebox.showwarning("提示", "请先选择匹配结果")
            return
        idx = sel[0]
        if idx >= len(self.engine.last_matches):
            messagebox.showwarning("提示", "该项不是坐标匹配结果")
            return
        m = self.engine.last_matches[idx]
        ok = self.engine.click(m.x, m.y)
        self.log(f"点击 点({m.x},{m.y}) px({m.px},{m.py}) {'成功' if ok else '失败(检查辅助功能权限)'}")

    # ---------- canvas: pick + crop ----------
    def _canvas_to_px(self, cx: int, cy: int) -> tuple[int, int]:
        if self._display_scale <= 0:
            return cx, cy
        return int(cx / self._display_scale), int(cy / self._display_scale)

    def on_canvas_press(self, event) -> None:
        if self._preview_img is None or self.engine.last_capture is None:
            return
        self._sel_start = (event.x, event.y)
        if self._sel_rect_id is not None:
            self.canvas.delete(self._sel_rect_id)
            self._sel_rect_id = None

    def on_canvas_drag(self, event) -> None:
        if not self._sel_start:
            return
        x0, y0 = self._sel_start
        if self._sel_rect_id is not None:
            self.canvas.delete(self._sel_rect_id)
        self._sel_rect_id = self.canvas.create_rectangle(x0, y0, event.x, event.y, outline="#0ff", width=2)

    def on_canvas_release(self, event) -> None:
        if self._preview_img is None or self.engine.last_capture is None or not self._sel_start:
            return
        x0, y0 = self._sel_start
        x1, y1 = event.x, event.y
        self._sel_start = None
        # 单击：取色
        if abs(x1 - x0) < 4 and abs(y1 - y0) < 4:
            self._crop_box_px = None
            px, py = self._canvas_to_px(x1, y1)
            bundle = self.engine.last_bundle
            if bundle is None:
                return
            pt_x, pt_y = bundle.px_to_point(px, py)
            bgr = self.engine.pixel_bgr(pt_x, pt_y)
            if bgr is None:
                self.lbl_info.configure(text=f"坐标越界 px({px},{py})")
                return
            b, g, r = bgr
            self.lbl_info.configure(
                text=(
                    f"逻辑点 ({pt_x},{pt_y}) 像素 ({px},{py})  "
                    f"BGR=({b},{g},{r}) RGB=({r},{g},{b})  #{r:02X}{g:02X}{b:02X}"
                )
            )
            self.log(f"取点 点({pt_x},{pt_y}) px({px},{py}) BGR=({b},{g},{r})")
            return
        # 拖拽：框选
        ax, bx = sorted((x0, x1))
        ay, by = sorted((y0, y1))
        px1, py1 = self._canvas_to_px(ax, ay)
        px2, py2 = self._canvas_to_px(bx, by)
        h, w = self.engine.last_capture.shape[:2]
        px1, py1 = max(0, px1), max(0, py1)
        px2, py2 = min(w, px2), min(h, py2)
        if px2 - px1 < 6 or py2 - py1 < 6:
            self.log("框选太小，已忽略")
            return
        self._crop_box_px = (px1, py1, px2, py2)
        bundle = self.engine.last_bundle
        if bundle:
            p1 = bundle.px_to_point(px1, py1)
            p2 = bundle.px_to_point(px2, py2)
            self.lbl_info.configure(
                text=f"已框选 px({px1},{py1})-({px2},{py2}) 点{p1}-{p2}  点「保存框选为用户模板」"
            )
            self.log(f"框选 px {px1},{py1}-{px2},{py2} 点 {p1}-{p2}")
        if self._sel_rect_id is not None:
            # 保持矩形显示
            pass

    def save_crop_template(self) -> None:
        if not self._crop_box_px or self.engine.last_capture is None:
            messagebox.showwarning("提示", "请先在预览图上拖拽框选区域")
            return
        name = self.var_crop_name.get().strip()
        if not name:
            name = simpledialog.askstring("模板名", "输入模板名（如 jb100 / color/red）") or ""
            name = name.strip()
        if not name:
            return
        x1, y1, x2, y2 = self._crop_box_px
        crop = self.engine.last_capture[y1:y2, x1:x2].copy()
        if crop.size == 0:
            messagebox.showerror("错误", "裁剪失败")
            return
        path = self.engine.save_user_template(name, crop)
        self.refresh_templates()
        # 自动选中
        stem = name[:-4] if name.endswith((".png", ".jpg", ".bmp")) else name
        try:
            vals = list(self.cmb_tpl["values"])
            if stem in vals:
                self.cmb_tpl.set(stem)
            elif name in vals:
                self.cmb_tpl.set(name)
        except Exception:
            pass
        self.log(f"用户模板已保存: {path} ({crop.shape[1]}x{crop.shape[0]})")
        messagebox.showinfo("提示", f"已保存用户模板\n{path}\n可立刻「测当前」验证")
        # 立即探测
        hit = self.engine.probe_template(stem, threshold=0.40)
        if hit:
            self._last_suggest = min(0.95, max(0.55, hit.score - 0.04))
            self.log(f"回测 {stem}: score={hit.score:.3f} 建议阈值≈{self._last_suggest:.2f}")
            self._fill_list([hit])
