"""Mac 图色/键鼠引擎 v2：Retina 安全坐标 + CG 窗口截图 + 多模式匹配。

设计目标（路线 B）：
- 截图像素坐标系与点击逻辑坐标系分离，并用 scale 正确换算
- 优先 CGWindowListCreateImage 按 window_id 截窗（比 mss 区域截更贴窗口）
- 用户自采模板优先于原版 Windows 模板
- 多尺度 + 灰度/彩色 模板匹配，提高可用率
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import cv2
import numpy as np

try:
    from AppKit import NSScreen
except Exception:  # pragma: no cover
    NSScreen = None

try:
    from Quartz import (
        CGDataProviderCopyData,
        CGImageGetBitsPerPixel,
        CGImageGetBytesPerRow,
        CGImageGetDataProvider,
        CGImageGetHeight,
        CGImageGetWidth,
        CGRectNull,
        CGWindowListCopyWindowInfo,
        CGWindowListCreateImage,
        kCGNullWindowID,
        kCGWindowImageBoundsIgnoreFraming,
        kCGWindowListOptionIncludingWindow,
        kCGWindowListOptionOnScreenOnly,
    )
except Exception:  # pragma: no cover
    CGWindowListCopyWindowInfo = None
    CGWindowListCreateImage = None
    kCGNullWindowID = None
    kCGWindowListOptionOnScreenOnly = None
    kCGWindowListOptionIncludingWindow = None
    kCGWindowImageBoundsIgnoreFraming = None

try:
    import mss
except Exception:  # pragma: no cover
    mss = None

try:
    from pynput.mouse import Button, Controller as MouseController
except Exception:  # pragma: no cover
    Button = None
    MouseController = None


# 模板相对截图的尺度搜索（覆盖网页缩放 / 模板尺寸差）
DEFAULT_SCALES = (
    0.50,
    0.60,
    0.67,
    0.75,
    0.80,
    0.90,
    1.00,
    1.10,
    1.25,
    1.50,
    1.75,
    2.00,
    2.50,
)


@dataclass
class WindowInfo:
    window_id: int
    title: str
    owner: str
    x: float  # 逻辑点
    y: float
    width: float
    height: float

    @property
    def bbox_points(self) -> dict[str, int]:
        return {
            "left": int(round(self.x)),
            "top": int(round(self.y)),
            "width": max(1, int(round(self.width))),
            "height": max(1, int(round(self.height))),
        }

    def label(self) -> str:
        t = self.title or "(无标题)"
        return f"[{self.owner}] {t} {int(self.width)}x{int(self.height)}"


@dataclass
class MatchResult:
    x: int  # 窗口内逻辑点坐标（用于点击）
    y: int
    score: float
    scale: float = 1.0
    name: str = ""
    method: str = "color"
    # 像素坐标（截图空间，便于画标注）
    px: int = 0
    py: int = 0

    @property
    def point(self) -> tuple[int, int]:
        return self.x, self.y


@dataclass
class CaptureBundle:
    """一次截窗结果：像素图 + 与逻辑点的换算。"""

    bgr: np.ndarray
    scale: float  # pixels / points
    point_w: float
    point_h: float
    origin_x: float
    origin_y: float

    @property
    def pixel_w(self) -> int:
        return int(self.bgr.shape[1])

    @property
    def pixel_h(self) -> int:
        return int(self.bgr.shape[0])

    def px_to_point(self, px: float, py: float) -> tuple[int, int]:
        if self.scale <= 0:
            return int(px), int(py)
        return int(round(px / self.scale)), int(round(py / self.scale))

    def point_to_px(self, x: float, y: float) -> tuple[int, int]:
        return int(round(x * self.scale)), int(round(y * self.scale))


class MacEngine:
    def __init__(
        self,
        assets: Path,
        threshold: float = 0.82,
        click_delay: float = 0.08,
        scales: Iterable[float] | None = None,
        debug_dir: Path | None = None,
        user_assets: Path | None = None,
    ) -> None:
        self.bundle_assets = Path(assets)
        if user_assets is not None:
            self.user_assets = Path(user_assets)
        else:
            # 开发默认：mac_port/user_templates；打包请由 App 传入 project_root()/user_templates
            self.user_assets = Path(assets).resolve().parents[2] / "user_templates"
        self.threshold = float(threshold)
        self.click_delay = float(click_delay)
        self.scales = tuple(scales) if scales else DEFAULT_SCALES
        self.debug_dir = Path(debug_dir) if debug_dir else None
        self._mouse = MouseController() if MouseController else None
        self._template_cache: dict[str, np.ndarray] = {}
        self.bind_window: Optional[WindowInfo] = None
        self.last_capture: Optional[np.ndarray] = None  # BGR 像素
        self.last_bundle: Optional[CaptureBundle] = None
        self.last_matches: list[MatchResult] = []
        self.last_error: str = ""
        self.prefer_cg = True

    # ---------- paths ----------
    def ensure_user_assets(self) -> Path:
        self.user_assets.mkdir(parents=True, exist_ok=True)
        (self.user_assets / "color").mkdir(exist_ok=True)
        (self.user_assets / "hero").mkdir(exist_ok=True)
        return self.user_assets

    def template_search_paths(self, name: str) -> list[Path]:
        name = name.replace("\\", "/").removeprefix("images/")
        rels = []
        if Path(name).suffix:
            rels.append(name)
        else:
            for ext in (".png", ".jpg", ".bmp"):
                rels.append(f"{name}{ext}")
        out: list[Path] = []
        for base in (self.user_assets, self.bundle_assets):
            for rel in rels:
                p = base / rel
                if p not in out:
                    out.append(p)
        return out

    def template_path(self, name: str) -> Optional[Path]:
        for p in self.template_search_paths(name):
            if p.exists():
                return p
        return None

    def list_templates(self) -> list[str]:
        names: set[str] = set()
        for base in (self.user_assets, self.bundle_assets):
            if not base.exists():
                continue
            for p in base.rglob("*.png"):
                rel = p.relative_to(base).as_posix()
                names.add(rel[:-4] if rel.endswith(".png") else rel)
        return sorted(names)

    def load_template(self, name: str) -> Optional[np.ndarray]:
        key = str(name)
        if key in self._template_cache:
            return self._template_cache[key]
        path = self.template_path(name)
        if not path:
            return None
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is not None:
            # 过小模板（原版 ok/zmui 仅几像素）在网页上极易误匹配，业务侧默认跳过
            if min(img.shape[:2]) < 8 or max(img.shape[:2]) < 12:
                self.last_error = f"模板过小已跳过: {name} {img.shape[1]}x{img.shape[0]}"
                return None
            self._template_cache[key] = img
        return img

    def clear_template_cache(self) -> None:
        self._template_cache.clear()

    def save_user_template(self, name: str, bgr: np.ndarray) -> Path:
        """保存用户自采模板（覆盖同名，优先于原版）。"""
        self.ensure_user_assets()
        name = name.replace("\\", "/").removeprefix("images/")
        if not name.endswith((".png", ".jpg", ".bmp")):
            name = f"{name}.png"
        path = self.user_assets / name
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), bgr)
        # 清缓存
        stem = name.rsplit(".", 1)[0]
        for k in list(self._template_cache.keys()):
            if k == stem or k == name or k.endswith(stem):
                self._template_cache.pop(k, None)
        self._template_cache.pop(stem, None)
        return path

    # ---------- display scale ----------
    @staticmethod
    def display_scale() -> float:
        if NSScreen is None:
            return 2.0
        try:
            return float(NSScreen.mainScreen().backingScaleFactor())
        except Exception:
            return 2.0

    # ---------- windows ----------
    def list_windows(self) -> list[WindowInfo]:
        if CGWindowListCopyWindowInfo is None:
            self.last_error = "Quartz 不可用"
            return []
        raw = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID) or []
        out: list[WindowInfo] = []
        skip_owners = {"Window Server", "Dock", "Control Center", "Notification Center", "SystemUIServer"}
        for item in raw:
            try:
                owner = str(item.get("kCGWindowOwnerName") or "")
                if owner in skip_owners:
                    continue
                bounds = item.get("kCGWindowBounds") or {}
                w = float(bounds.get("Width", 0) or 0)
                h = float(bounds.get("Height", 0) or 0)
                if w < 100 or h < 80:
                    continue
                # 分层太高的菜单等可跳过：layer!=0 时很多是浮层
                layer = int(item.get("kCGWindowLayer") or 0)
                if layer != 0:
                    continue
                wid = int(item.get("kCGWindowNumber") or 0)
                if not wid:
                    continue
                out.append(
                    WindowInfo(
                        window_id=wid,
                        title=str(item.get("kCGWindowName") or ""),
                        owner=owner,
                        x=float(bounds.get("X", 0) or 0),
                        y=float(bounds.get("Y", 0) or 0),
                        width=w,
                        height=h,
                    )
                )
            except Exception:
                continue
        out.sort(key=lambda w: w.width * w.height, reverse=True)
        return out

    def find_window(self, keywords: Iterable[str]) -> Optional[WindowInfo]:
        kws = [k.lower() for k in keywords if k]
        best: Optional[WindowInfo] = None
        best_score = -1
        for win in self.list_windows():
            text = f"{win.title} {win.owner}".lower()
            score = sum(1 for k in kws if k in text)
            if score > 0:
                score = score * 1_000_000 + int(win.width * win.height)
                if score > best_score:
                    best, best_score = win, score
        self.bind_window = best
        return best

    def bind_by_id(self, window_id: int) -> Optional[WindowInfo]:
        for win in self.list_windows():
            if win.window_id == window_id:
                self.bind_window = win
                return win
        return None

    def refresh_bind(self) -> Optional[WindowInfo]:
        if not self.bind_window:
            return None
        for win in self.list_windows():
            if win.window_id == self.bind_window.window_id:
                self.bind_window = win
                return win
        keys = [self.bind_window.title, self.bind_window.owner]
        return self.find_window([k for k in keys if k])

    # ---------- capture ----------
    def _cgimage_to_bgr(self, cgimg) -> Optional[np.ndarray]:
        if cgimg is None:
            return None
        try:
            width = int(CGImageGetWidth(cgimg))
            height = int(CGImageGetHeight(cgimg))
            bpr = int(CGImageGetBytesPerRow(cgimg))
            bpp = int(CGImageGetBitsPerPixel(cgimg))
            data = CGDataProviderCopyData(CGImageGetDataProvider(cgimg))
            if not data or width <= 0 or height <= 0:
                return None
            buf = np.frombuffer(bytes(data), dtype=np.uint8)
            if bpp == 32:
                row_px = bpr // 4
                arr = buf.reshape((height, row_px, 4))[:, :width, :]
                # macOS 通常是 BGRA 或 RGBA；用 alpha 在末尾假设 BGRA→BGR
                bgr = cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
                return bgr
            if bpp == 24:
                row_px = bpr // 3
                arr = buf.reshape((height, row_px, 3))[:, :width, :]
                return arr.copy()
            self.last_error = f"不支持的像素格式 bpp={bpp}"
            return None
        except Exception as e:
            self.last_error = f"CGImage 转换失败: {e}"
            return None

    def capture_cg(self, win: WindowInfo) -> Optional[CaptureBundle]:
        if CGWindowListCreateImage is None:
            return None
        try:
            cgimg = CGWindowListCreateImage(
                CGRectNull,
                kCGWindowListOptionIncludingWindow,
                int(win.window_id),
                kCGWindowImageBoundsIgnoreFraming,
            )
            bgr = self._cgimage_to_bgr(cgimg)
            if bgr is None:
                return None
            # scale = 像素 / 逻辑点
            scale_x = bgr.shape[1] / max(win.width, 1.0)
            scale_y = bgr.shape[0] / max(win.height, 1.0)
            scale = float((scale_x + scale_y) / 2.0)
            if scale < 0.5:
                scale = self.display_scale()
            return CaptureBundle(
                bgr=bgr,
                scale=scale,
                point_w=win.width,
                point_h=win.height,
                origin_x=win.x,
                origin_y=win.y,
            )
        except Exception as e:
            self.last_error = f"CG 截窗失败: {e}"
            return None

    def capture_mss(self, win: WindowInfo) -> Optional[CaptureBundle]:
        if mss is None:
            self.last_error = "mss 不可用"
            return None
        try:
            region = win.bbox_points
            # 兼容 mss.MSS 与旧 mss.mss
            grabber = mss.MSS() if hasattr(mss, "MSS") else mss.mss()
            with grabber as sct:
                shot = sct.grab(region)
                img = np.array(shot)  # BGRA
                bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            # mss 在 Retina 上常返回逻辑分辨率；scale≈1 相对 points
            scale_x = bgr.shape[1] / max(win.width, 1.0)
            scale_y = bgr.shape[0] / max(win.height, 1.0)
            scale = float((scale_x + scale_y) / 2.0) or 1.0
            return CaptureBundle(
                bgr=bgr,
                scale=scale,
                point_w=win.width,
                point_h=win.height,
                origin_x=win.x,
                origin_y=win.y,
            )
        except Exception as e:
            self.last_error = f"mss 截图失败: {e}"
            return None

    def capture_bundle(self) -> Optional[CaptureBundle]:
        win = self.refresh_bind() or self.bind_window
        if not win:
            self.last_error = "未绑定窗口"
            return None
        bundle = None
        if self.prefer_cg:
            bundle = self.capture_cg(win)
        if bundle is None:
            bundle = self.capture_mss(win)
        if bundle is None:
            return None
        self.last_bundle = bundle
        self.last_capture = bundle.bgr
        self.last_error = ""
        return bundle

    def capture(self, region: Optional[tuple[int, int, int, int]] = None) -> Optional[np.ndarray]:
        """兼容旧 API：返回 BGR 像素图。region 为窗口内逻辑点 (x,y,w,h)。"""
        bundle = self.capture_bundle()
        if bundle is None:
            return None
        if not region:
            return bundle.bgr
        x, y, w, h = region
        x1, y1 = bundle.point_to_px(x, y)
        x2, y2 = bundle.point_to_px(x + w, y + h)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(bundle.pixel_w, x2), min(bundle.pixel_h, y2)
        if x2 <= x1 or y2 <= y1:
            return None
        return bundle.bgr[y1:y2, x1:x2].copy()

    def save_capture(self, path: Path | str, annotated: bool = False) -> Optional[Path]:
        img = self.last_capture if self.last_capture is not None else self.capture()
        if img is None:
            return None
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        vis = img.copy()
        if annotated and self.last_matches and self.last_bundle:
            for m in self.last_matches:
                px, py = m.px, m.py
                if px == 0 and py == 0 and self.last_bundle:
                    px, py = self.last_bundle.point_to_px(m.x, m.y)
                cv2.circle(vis, (px, py), max(8, int(10 * self.last_bundle.scale)), (0, 0, 255), 2)
                cv2.putText(
                    vis,
                    f"{m.name}:{m.score:.2f}",
                    (px + 8, max(16, py - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5 * max(1.0, self.last_bundle.scale / 2),
                    (0, 255, 0),
                    1,
                    cv2.LINE_AA,
                )
        cv2.imwrite(str(out), vis)
        return out

    # ---------- matching ----------
    def _match_template_raw(
        self,
        screen: np.ndarray,
        tpl: np.ndarray,
        threshold: float,
    ) -> Optional[tuple[int, int, float, float, str]]:
        """返回 (px, py, score, scale, method) 像素中心。"""
        best: Optional[tuple[int, int, float, float, str]] = None
        sh, sw = screen.shape[:2]
        screen_gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        tpl_gray_full = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)

        for scale in self.scales:
            tw = max(1, int(round(tpl.shape[1] * scale)))
            th = max(1, int(round(tpl.shape[0] * scale)))
            if tw >= sw or th >= sh or tw < 6 or th < 6:
                continue
            interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
            tpl_c = tpl if abs(scale - 1.0) < 1e-6 else cv2.resize(tpl, (tw, th), interpolation=interp)
            tpl_g = tpl_gray_full if abs(scale - 1.0) < 1e-6 else cv2.resize(tpl_gray_full, (tw, th), interpolation=interp)

            for method_name, hay, needle in (
                ("color", screen, tpl_c),
                ("gray", screen_gray, tpl_g),
            ):
                try:
                    res = cv2.matchTemplate(hay, needle, cv2.TM_CCOEFF_NORMED)
                except Exception:
                    continue
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val < threshold:
                    continue
                cx = int(max_loc[0] + needle.shape[1] / 2)
                cy = int(max_loc[1] + needle.shape[0] / 2)
                cand = (cx, cy, float(max_val), float(scale), method_name)
                if best is None:
                    best = cand
                else:
                    # 得分明显更高则采用；几乎持平时优先接近 1.0 的尺度（减少纯色/模糊误配）
                    if max_val > best[2] + 0.008:
                        best = cand
                    elif abs(max_val - best[2]) <= 0.008 and abs(scale - 1.0) < abs(best[3] - 1.0):
                        best = cand
        return best

    def _to_match_result(
        self,
        bundle: CaptureBundle,
        name: str,
        raw: tuple[int, int, float, float, str],
    ) -> MatchResult:
        px, py, score, scale, method = raw
        x, y = bundle.px_to_point(px, py)
        return MatchResult(
            x=x,
            y=y,
            score=score,
            scale=scale,
            name=name,
            method=method,
            px=px,
            py=py,
        )

    def find_pic_ex(
        self,
        name: str,
        threshold: Optional[float] = None,
        region: Optional[tuple[int, int, int, int]] = None,
        bundle: Optional[CaptureBundle] = None,
    ) -> Optional[MatchResult]:
        bundle = bundle or self.capture_bundle()
        tpl = self.load_template(name)
        if bundle is None or tpl is None:
            if tpl is None:
                self.last_error = f"模板不存在: {name}"
            return None
        th = self.threshold if threshold is None else float(threshold)
        screen = bundle.bgr
        off_px = (0, 0)
        if region:
            x, y, w, h = region
            x1, y1 = bundle.point_to_px(x, y)
            x2, y2 = bundle.point_to_px(x + w, y + h)
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(bundle.pixel_w, x2), min(bundle.pixel_h, y2)
            screen = bundle.bgr[y1:y2, x1:x2]
            off_px = (x1, y1)
            if screen.size == 0:
                return None
        raw = self._match_template_raw(screen, tpl, th)
        if not raw:
            self.last_matches = []
            return None
        px, py, score, scale, method = raw
        px += off_px[0]
        py += off_px[1]
        hit = self._to_match_result(bundle, name, (px, py, score, scale, method))
        self.last_matches = [hit]
        return hit

    def find_pic(
        self,
        name: str,
        threshold: Optional[float] = None,
        region: Optional[tuple[int, int, int, int]] = None,
    ) -> Optional[tuple[int, int, float]]:
        hit = self.find_pic_ex(name, threshold=threshold, region=region)
        if not hit:
            return None
        return hit.x, hit.y, hit.score

    def find_pic_all_ex(
        self,
        name: str,
        threshold: Optional[float] = None,
        region: Optional[tuple[int, int, int, int]] = None,
        nms_dist_points: int = 14,
        bundle: Optional[CaptureBundle] = None,
    ) -> list[MatchResult]:
        bundle = bundle or self.capture_bundle()
        tpl = self.load_template(name)
        if bundle is None or tpl is None:
            return []
        th = self.threshold if threshold is None else float(threshold)
        screen = bundle.bgr
        off_px = (0, 0)
        if region:
            x, y, w, h = region
            x1, y1 = bundle.point_to_px(x, y)
            x2, y2 = bundle.point_to_px(x + w, y + h)
            screen = bundle.bgr[max(0, y1) : min(bundle.pixel_h, y2), max(0, x1) : min(bundle.pixel_w, x2)]
            off_px = (max(0, x1), max(0, y1))
        sh, sw = screen.shape[:2]
        screen_gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        pts: list[MatchResult] = []
        nms_px = max(6, int(nms_dist_points * bundle.scale))
        for scale in self.scales:
            tw = max(1, int(round(tpl.shape[1] * scale)))
            thh = max(1, int(round(tpl.shape[0] * scale)))
            if tw >= sw or thh >= sh or tw < 6 or thh < 6:
                continue
            interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
            needle = cv2.resize(cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY), (tw, thh), interpolation=interp)
            try:
                res = cv2.matchTemplate(screen_gray, needle, cv2.TM_CCOEFF_NORMED)
            except Exception:
                continue
            ys, xs = np.where(res >= th)
            for x0, y0 in zip(xs.tolist(), ys.tolist()):
                score = float(res[y0, x0])
                px = int(x0 + needle.shape[1] / 2) + off_px[0]
                py = int(y0 + needle.shape[0] / 2) + off_px[1]
                pts.append(self._to_match_result(bundle, name, (px, py, score, float(scale), "gray")))
        pts.sort(key=lambda p: p.score, reverse=True)
        kept: list[MatchResult] = []
        for p in pts:
            if all(abs(p.px - k.px) + abs(p.py - k.py) >= nms_px for k in kept):
                kept.append(p)
        self.last_matches = kept
        return kept

    def find_pic_all(
        self,
        name: str,
        threshold: Optional[float] = None,
        region: Optional[tuple[int, int, int, int]] = None,
        nms_dist: int = 12,
    ) -> list[tuple[int, int, float]]:
        hits = self.find_pic_all_ex(name, threshold=threshold, region=region, nms_dist_points=nms_dist)
        return [(h.x, h.y, h.score) for h in hits]

    def probe_template(self, name: str, threshold: float = 0.45) -> Optional[MatchResult]:
        return self.find_pic_ex(name, threshold=threshold)

    def probe_many(self, names: Iterable[str], threshold: float = 0.45) -> list[MatchResult]:
        bundle = self.capture_bundle()
        if bundle is None:
            return []
        results: list[MatchResult] = []
        for name in names:
            hit = self.find_pic_ex(name, threshold=threshold, bundle=bundle)
            if hit:
                results.append(hit)
        results.sort(key=lambda r: r.score, reverse=True)
        self.last_matches = results
        # 重新画在同一张图上
        return results

    def ishas(self, name: str, threshold: Optional[float] = None) -> bool:
        return self.find_pic_ex(name, threshold=threshold) is not None

    def suggest_threshold(self, name: str) -> Optional[float]:
        hit = self.probe_template(name, threshold=0.30)
        if not hit:
            return None
        # 业务阈值建议：得分减一点容差，夹在 [0.55, 0.95]
        return float(min(0.95, max(0.55, hit.score - 0.04)))

    def pipeline_check_recruit(self) -> dict:
        """抽卡主链路自检：以「金币招募按钮」高置信命中为准，避免小模板误报。"""
        bundle = self.capture_bundle()
        report = {
            "ok": False,
            "scene": "unknown",
            "hint": "",
            "scale": None if not bundle else bundle.scale,
            "size": None if not bundle else f"{bundle.pixel_w}x{bundle.pixel_h}",
            "items": [],
            "error": self.last_error,
        }
        if not bundle:
            return report
        # 阈值分组：金币按钮要严，UI 装饰可松
        checks = [
            ("金币按钮", ["jb100", "jb90", "jb0"], 0.72),
            ("进入按钮", ["jinru"], 0.70),
            ("招募UI", ["cgzm", "zm", "zmui1", "zmui2"], 0.78),
            ("确认", ["ok", "ok2"], 0.80),
            ("颜色", ["color/red", "color/golden", "color/purple", "color/blue", "color/white"], 0.75),
            ("钻石", ["zs", "zs_top", "jb100_h", "hongqi"], 0.78),
        ]
        items = []
        scores: dict[str, float] = {}
        for group, names, th in checks:
            best = None
            for n in names:
                hit = self.find_pic_ex(n, threshold=th, bundle=bundle)
                if hit and (best is None or hit.score > best.score):
                    best = hit
            if best:
                scores[group] = best.score
                items.append(
                    {
                        "group": group,
                        "name": best.name,
                        "score": round(best.score, 3),
                        "xy": (best.x, best.y),
                        "suggest_th": round(min(0.95, max(0.55, best.score - 0.04)), 3),
                        "source": (
                            "user"
                            if self.template_path(best.name) and str(self.user_assets) in str(self.template_path(best.name))
                            else "bundle"
                        ),
                    }
                )
            else:
                items.append(
                    {"group": group, "name": None, "score": 0.0, "xy": None, "suggest_th": None, "source": None}
                )
        report["items"] = items
        btn_ok = scores.get("金币按钮", 0) >= 0.72
        enter_ok = scores.get("进入按钮", 0) >= 0.70
        report["ok"] = btn_ok
        if btn_ok:
            report["scene"] = "recruit"
            report["hint"] = "已识别金币招募按钮，可在抽卡页开始"
        elif enter_ok:
            report["scene"] = "activity_enter"
            report["hint"] = "当前像活动/关卡页（有「进入」），请先点进入，再进主界面打开招募"
        else:
            report["scene"] = "not_recruit"
            report["hint"] = (
                "未识别到金币招募按钮。请手动进入「招募」界面；"
                "或在校准页框选真实按钮保存为 jb100/jb90/jb0"
            )
        self.last_matches = [
            MatchResult(x=i["xy"][0], y=i["xy"][1], score=i["score"], name=i["name"] or "")
            for i in items
            if i.get("xy")
        ]
        return report

    def multi_color_match(
        self,
        points: list[tuple[int, int, tuple[int, int, int], int]],
    ) -> bool:
        bundle = self.capture_bundle()
        if bundle is None:
            return False
        for x, y, bgr, tol in points:
            px, py = bundle.point_to_px(x, y)
            if px < 0 or py < 0 or px >= bundle.pixel_w or py >= bundle.pixel_h:
                return False
            pixel = bundle.bgr[py, px]
            if any(abs(int(pixel[i]) - int(bgr[i])) > tol for i in range(3)):
                return False
        return True

    def pixel_bgr(self, x: int, y: int) -> Optional[tuple[int, int, int]]:
        """x,y 为窗口逻辑点。"""
        bundle = self.last_bundle or self.capture_bundle()
        if bundle is None:
            return None
        px, py = bundle.point_to_px(x, y)
        if px < 0 or py < 0 or px >= bundle.pixel_w or py >= bundle.pixel_h:
            return None
        b, g, r = bundle.bgr[py, px]
        return int(b), int(g), int(r)

    def crop_points(self, x1: int, y1: int, x2: int, y2: int) -> Optional[np.ndarray]:
        """按逻辑点矩形裁剪当前截图。"""
        bundle = self.last_bundle or self.capture_bundle()
        if bundle is None:
            return None
        xa, xb = sorted((x1, x2))
        ya, yb = sorted((y1, y2))
        px1, py1 = bundle.point_to_px(xa, ya)
        px2, py2 = bundle.point_to_px(xb, yb)
        px1, py1 = max(0, px1), max(0, py1)
        px2, py2 = min(bundle.pixel_w, px2), min(bundle.pixel_h, py2)
        if px2 - px1 < 4 or py2 - py1 < 4:
            return None
        return bundle.bgr[py1:py2, px1:px2].copy()

    # ---------- input（逻辑点） ----------
    def _abs_point(self, x: float, y: float) -> tuple[float, float]:
        win = self.refresh_bind() or self.bind_window
        if not win:
            return float(x), float(y)
        return float(win.x + x), float(win.y + y)

    def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> bool:
        if self._mouse is None:
            self.last_error = "鼠标控制不可用（检查辅助功能权限）"
            return False
        ax, ay = self._abs_point(x, y)
        btn = Button.left if button == "left" else Button.right
        try:
            self._mouse.position = (ax, ay)
            time.sleep(self.click_delay)
            for _ in range(clicks):
                self._mouse.click(btn, 1)
                time.sleep(self.click_delay)
            return True
        except Exception as e:
            self.last_error = f"点击失败: {e}"
            return False

    def click_pic(self, name: str, threshold: Optional[float] = None) -> bool:
        hit = self.find_pic_ex(name, threshold=threshold)
        if not hit:
            return False
        return self.click(hit.x, hit.y)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.35, steps: int = 20) -> bool:
        if self._mouse is None:
            return False
        ax1, ay1 = self._abs_point(x1, y1)
        ax2, ay2 = self._abs_point(x2, y2)
        self._mouse.position = (ax1, ay1)
        time.sleep(0.05)
        self._mouse.press(Button.left)
        for i in range(1, steps + 1):
            t = i / steps
            self._mouse.position = (ax1 + (ax2 - ax1) * t, ay1 + (ay2 - ay1) * t)
            time.sleep(duration / steps)
        self._mouse.release(Button.left)
        return True

    def wait_pic(
        self,
        name: str,
        timeout: float = 8.0,
        threshold: Optional[float] = None,
        interval: float = 0.3,
    ) -> Optional[tuple[int, int, float]]:
        end = time.time() + timeout
        while time.time() < end:
            hit = self.find_pic(name, threshold=threshold)
            if hit:
                return hit
            time.sleep(interval)
        return None

    def diagnostics(self) -> dict:
        win = self.bind_window
        bundle = self.last_bundle
        return {
            "display_scale": self.display_scale(),
            "window": None if not win else win.label(),
            "window_id": None if not win else win.window_id,
            "capture_scale": None if not bundle else bundle.scale,
            "capture_px": None if not bundle else f"{bundle.pixel_w}x{bundle.pixel_h}",
            "user_assets": str(self.user_assets),
            "bundle_assets": str(self.bundle_assets),
            "threshold": self.threshold,
            "last_error": self.last_error,
            "template_count": len(self.list_templates()),
        }
