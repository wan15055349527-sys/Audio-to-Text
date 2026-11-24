# 听稿 v0.2.2

Windows 11 x64 本地音视频转写工具。导入页与回听页使用蓝紫配色，播放器显示会随播放状态变化的极光。文件在本机解码、识别和保存。

## 直接使用

1. 解压完整 ZIP，双击 `TingGao.exe`。
2. 选择或拖入音频和视频。需要时选择识别语言，点击「开始转写」。
3. 点片段左边的时间回听。双击正文、修改并保存。用「中文复核」比较同一片段的 Paraformer 结果。
4. 从右上角导出 TXT 或 SRT。关闭后可以重新打开稿件。

两个模型已随便携版提供。Windows 11 自带 Microsoft Edge WebView2，桌面窗口使用这个组件。若系统镜像已移除它，可从 [微软 WebView2 下载页](https://developer.microsoft.com/microsoft-edge/webview2/#download) 恢复。转写在 CPU 上运行。

工作稿和试听缓存保存在 `%LOCALAPPDATA%\TingGao`。通过「选择文件」导入会记录原始文件的位置。拖入文件时会复制一份到该目录，用于重启后重试。界面上的「停止」会在当前解码或识别步骤结束后生效。

## 修改和重新打包

- `web/index.html` 和 `web/desk.css` 控制布局与果冻主题，`web/desk.js` 控制交互。
- `engines.py` 加载本地模型，`library.py` 管理稿件和队列，`launch.py` 启动桌面窗口。
- 源码包使用 Python 3.13 x64。先运行 `python -m pip install -r requirements.txt`。
- 把便携版的 `models` 文件夹放在源码目录，运行 `python launch.py` 调试，或在 PowerShell 运行 `./build.ps1` 打包。
- 若模型目录在其他位置，把绝对路径赋给 `$env:TINGGAO_MODELS` 再运行构建脚本。输出在 `build/dist/TingGao`，发布时压缩整个文件夹。

