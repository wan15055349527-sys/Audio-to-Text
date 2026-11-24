# 听稿安装程序
安装器以 v0.2 的 Windows 便携 ZIP 为内容，默认使用当前用户的 LocalAppData。它支持通过文件夹选择器设置目录、选择桌面快捷方式，以及替换同一目录内的上个版本。稿件继续保存在用户数据目录。

重新打包时，在本机虚拟环境安装 PyInstaller，将原便携 ZIP 复制为本目录下的 payload.zip，运行 `python icon.py`，再运行以下命令。

```powershell
python -m PyInstaller --onefile --windowed --noupx --name TingGao-Setup-x64-v0.2.1 --icon tinggao.ico --add-data "payload.zip;." --add-data "tinggao.ico;." setup.py
```
