"""配置默认值与读写（对齐原版 config.ini / cfgwr 行为）。"""

from __future__ import annotations

import configparser
from copy import deepcopy
from pathlib import Path
from typing import Any

APP_VERSION = "1.58-mac.0.4"
APP_TITLE = f"百炼英雄助手 Mac版 v{APP_VERSION}"

# 原版模板图对应的英雄名（用于 UI / 结果统计）
HERO_NAMES = {
    "yase": "亚瑟",
    "libai": "李白",
    "tianshi": "天使",
    "wangzi": "王子",
    "baiwuchang": "白无常",
    "wuji": "舞姬",
    "shimaoge": "史矛革",
    "shuangqiang": "双枪",
    "kaer": "卡尔",
    "kakaxi": "卡卡西",
    "lieren": "猎人",
    "yinfa": "银发",
    "jiushen": "酒神",
    "gandaofu": "甘道夫",
    "tieniangzi": "铁娘子",
    "lina": "莉娜",
    "deluyi": "德鲁伊",
    "jier": "吉尔",
    "heiguafu": "黑寡妇",
    "aobing": "敖丙",
    "shengqi": "圣骑",
    "yuanyi": "缘壹",
}

COLOR_ORDER = ["white", "blue", "purple", "golden", "red"]
COLOR_CN = {
    "white": "白",
    "blue": "蓝",
    "purple": "紫",
    "golden": "金",
    "red": "红",
}

DEFAULT_CONFIG: dict[str, Any] = {
    "platform": "web",  # web | wechat（Mac 上 wechat 需手动把小程序窗置前）
    "window_title_keywords": ["百炼英雄", "微信", "WeChat", "Chrome", "Safari", "Edge", "浏览器"],
    "threshold": 0.82,
    "click_delay": 0.08,
    "loop_delay": 0.25,
    "cards": {
        "enabled_heroes": list(HERO_NAMES.keys()),
        "cards_count": 0,  # 0 = 无限
        "fast_zm": False,
        "bd_h_stop": True,
        "h_stop": False,
        "h_stop_num": 1,
        "triple": False,
    },
    "coins": {
        "mode": "default",  # default | custom
        "default_bosses": ["疯牛魔王", "树精长老", "剧毒蝎王"],
        "selected_bosses": ["疯牛魔王"],
        "start_min": 0,
        "end_min": 0,
        "restart_min": 0,
        "refresh_mode": "王座刷新",
        "custom_script": (
            "# 自定义刷图脚本示例\n"
            "# 支持指令：传送 名称 | 移动 方向 秒 | 等待 秒 | 回城 | 开宝箱 | 点击 x y | 重启 | 停止 | 跳转 行号\n"
            "等待 2\n"
            "传送 疯牛魔王\n"
            "等待 1\n"
            "移动 右下 3.5\n"
            "开宝箱\n"
            "回城\n"
        ),
    },
    "sys": {
        "jjc_num": 1,
        "jjc_count": 10,
        "random_btn": True,
    },
    "game_url": "https://mprogram.boomegg.cn/box/game/wx77200645d1c7f35f/h5?appid=wx77200645d1c7f35f",
    "last_url": "",
}


def project_root() -> Path:
    """开发时为 mac_port/；打包成 .app 时写到用户目录，避免 bundle 只读。"""
    import sys

    if getattr(sys, "frozen", False):
        return Path.home() / "Library" / "Application Support" / "BlyxMac"
    return Path(__file__).resolve().parent.parent


def bundle_dir() -> Path:
    """代码与资源所在目录（开发=源码包；打包= _MEIPASS 或 app 内）。"""
    import sys

    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def assets_dir() -> Path:
    # 打包后 add-data 到 blyx_mac/assets/images
    cand = Path(__file__).resolve().parent / "assets" / "images"
    if cand.exists():
        return cand
    return bundle_dir() / "blyx_mac" / "assets" / "images"


def user_templates_dir() -> Path:
    """用户自采模板目录（优先于原版 bundle 模板）。"""
    p = project_root() / "user_templates"
    p.mkdir(parents=True, exist_ok=True)
    (p / "color").mkdir(exist_ok=True)
    (p / "hero").mkdir(exist_ok=True)
    return p


def config_path() -> Path:
    root = project_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / "config.ini"


def script_path() -> Path:
    root = project_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / "script.json"


def log_path() -> Path:
    root = project_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / "error.log"


class ConfigStore:
    """简单配置仓库：内存 dict + config.ini 持久化。"""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_path()
        self.data: dict[str, Any] = deepcopy(DEFAULT_CONFIG)
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.save()
            return
        cp = configparser.ConfigParser()
        try:
            cp.read(self.path, encoding="utf-8")
        except Exception:
            self.data = deepcopy(DEFAULT_CONFIG)
            self.save()
            return

        g = cp["general"] if cp.has_section("general") else {}
        self.data["platform"] = g.get("platform", self.data["platform"])
        self.data["threshold"] = float(g.get("threshold", self.data["threshold"]))
        self.data["click_delay"] = float(g.get("click_delay", self.data["click_delay"]))
        self.data["loop_delay"] = float(g.get("loop_delay", self.data["loop_delay"]))
        self.data["game_url"] = g.get("game_url", self.data["game_url"])
        self.data["last_url"] = g.get("last_url", self.data["last_url"])
        kws = g.get("window_title_keywords", "")
        if kws:
            self.data["window_title_keywords"] = [x.strip() for x in kws.split("|") if x.strip()]

        if cp.has_section("cards"):
            c = cp["cards"]
            heroes = c.get("enabled_heroes", "")
            if heroes:
                self.data["cards"]["enabled_heroes"] = [x for x in heroes.split(",") if x]
            self.data["cards"]["cards_count"] = int(c.get("cards_count", 0))
            self.data["cards"]["fast_zm"] = c.getboolean("fast_zm", False)
            self.data["cards"]["bd_h_stop"] = c.getboolean("bd_h_stop", True)
            self.data["cards"]["h_stop"] = c.getboolean("h_stop", False)
            self.data["cards"]["h_stop_num"] = int(c.get("h_stop_num", 1))
            self.data["cards"]["triple"] = c.getboolean("triple", False)

        if cp.has_section("coins"):
            c = cp["coins"]
            self.data["coins"]["mode"] = c.get("mode", "default")
            bosses = c.get("selected_bosses", "")
            if bosses:
                self.data["coins"]["selected_bosses"] = [x for x in bosses.split(",") if x]
            self.data["coins"]["start_min"] = int(c.get("start_min", 0))
            self.data["coins"]["end_min"] = int(c.get("end_min", 0))
            self.data["coins"]["restart_min"] = int(c.get("restart_min", 0))
            self.data["coins"]["refresh_mode"] = c.get("refresh_mode", "王座刷新")
            script_file = self.path.parent / "custom_script.txt"
            if script_file.exists():
                self.data["coins"]["custom_script"] = script_file.read_text(encoding="utf-8")

        if cp.has_section("sys"):
            c = cp["sys"]
            self.data["sys"]["jjc_num"] = int(c.get("jjc_num", 1))
            self.data["sys"]["jjc_count"] = int(c.get("jjc_count", 10))
            self.data["sys"]["random_btn"] = c.getboolean("random_btn", True)

    def save(self) -> None:
        cp = configparser.ConfigParser()
        cp["general"] = {
            "platform": str(self.data["platform"]),
            "threshold": str(self.data["threshold"]),
            "click_delay": str(self.data["click_delay"]),
            "loop_delay": str(self.data["loop_delay"]),
            "game_url": str(self.data["game_url"]),
            "last_url": str(self.data.get("last_url", "")),
            "window_title_keywords": "|".join(self.data["window_title_keywords"]),
        }
        cards = self.data["cards"]
        cp["cards"] = {
            "enabled_heroes": ",".join(cards["enabled_heroes"]),
            "cards_count": str(cards["cards_count"]),
            "fast_zm": str(cards["fast_zm"]),
            "bd_h_stop": str(cards["bd_h_stop"]),
            "h_stop": str(cards["h_stop"]),
            "h_stop_num": str(cards["h_stop_num"]),
            "triple": str(cards["triple"]),
        }
        coins = self.data["coins"]
        cp["coins"] = {
            "mode": str(coins["mode"]),
            "selected_bosses": ",".join(coins["selected_bosses"]),
            "start_min": str(coins["start_min"]),
            "end_min": str(coins["end_min"]),
            "restart_min": str(coins["restart_min"]),
            "refresh_mode": str(coins["refresh_mode"]),
        }
        syscfg = self.data["sys"]
        cp["sys"] = {
            "jjc_num": str(syscfg["jjc_num"]),
            "jjc_count": str(syscfg["jjc_count"]),
            "random_btn": str(syscfg["random_btn"]),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            cp.write(f)
        script_file = self.path.parent / "custom_script.txt"
        script_file.write_text(coins.get("custom_script", ""), encoding="utf-8")

    def get(self) -> dict[str, Any]:
        return self.data
