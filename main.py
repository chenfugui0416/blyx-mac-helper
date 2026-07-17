#!/usr/bin/env python3
"""百炼英雄 Mac 移植版入口。"""

from __future__ import annotations

import multiprocessing
import tkinter as tk

from blyx_mac import __version__
from blyx_mac.ui.app import App


def main() -> None:
    multiprocessing.freeze_support()
    root = tk.Tk()
    # 尝试改善 Retina 下字体
    try:
        root.tk.call("tk", "scaling", 1.5)
    except Exception:
        pass
    App(root, __version__)
    root.mainloop()


if __name__ == "__main__":
    main()
