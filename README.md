# 百炼英雄辅助（Mac）

版本：`1.58-mac.0.4`

macOS 上的「百炼英雄」网页/H5 辅助工具：截窗识别 + 键鼠模拟。  
按 Windows 工具结构重写，**不连接**任何卡密服务器。

## 重要说明

- **不是** exe 转译 / 不是虚拟机方案；本机 Python / 可打包 `.app`。
- 引擎：CG 按窗截图 + Retina 点/像素换算 + 多尺度模板匹配 + pynput 点击。
- 游戏请用**官方网页/H5**自行登录；本工具只操作你已打开的窗口。
- 原版 Windows 小图模板在 Mac 上常对不齐：请到「校准」页框选保存到 `user_templates/`。
- **抽卡前必须进入「招募」界面**（能看到金币招募按钮）；活动页/大地图上直接开始会空转。

## 环境与权限

- macOS + Python 3.10+（推荐 arm64）
- **系统设置 → 隐私与安全性**
  - **屏幕录制**（给 Terminal / Python / 本 App）
  - **辅助功能**（点击）
  - **输入监控**（录制页需要）

## 源码启动

```bash
git clone https://github.com/chenfugui0416/blyx-mac-helper.git
cd blyx-mac-helper
python3 -m pip install -r requirements.txt
python3 main.py
```

## 推荐使用顺序

1. 浏览器打开并登录游戏，进入 **招募** 界面。
2. 打开本工具 → **校准**
   - 刷新窗口 / 绑定 Chrome「百炼英雄」
   - **截图预览** → **招募链路自检**
   - 未命中金币按钮：预览拖拽框选 → 命名 `jb100`/`jb90`/`jb0` → 保存用户模板
3. **抽卡** 页次数先填 `1`～`3`，点 **开始**。
4. （可选）录制自定义刷图脚本 → 写入金币页。

> 「测全部」阈值很低，结果里会有大量噪声，**不要**用它判断能不能抽卡。以链路自检的「金币按钮」为准。

## 打包 App

```bash
bash scripts/build_app.sh
# 产物：dist/百炼英雄Mac.app
# 签名失败时：
#   xattr -cr dist/百炼英雄Mac.app && codesign --force --deep --sign - dist/百炼英雄Mac.app
```

配置写入：

- 源码运行：项目目录 `config.ini`
- `.app`：`~/Library/Application Support/BlyxMac/config.ini`

## 目录

```
.
  main.py
  requirements.txt
  README.md
  scripts/build_app.sh
  blyx_mac/
    engine/mac_engine.py   # 引擎
    models/                # 抽卡 / 刷金 / 竞技场
    ui/                    # 主界面 / 校准 / 录制
    assets/images/         # 内置模板
  user_templates/          # 你自采的模板（优先，默认不提交）
```

## 合规

仅供学习与自用研究。请遵守游戏服务条款与当地法律。作者不对滥用后果负责。
