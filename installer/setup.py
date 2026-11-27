"""Install the verified TingGao release for the current Windows user."""

import argparse
import ctypes as c
from ctypes import wintypes as w
from pathlib import Path
from queue import Empty, SimpleQueue
from shutil import copyfile, rmtree
import os
import json
import subprocess
from threading import Thread
import tkinter as tk
from tkinter import filedialog, ttk
from uuid import UUID, uuid4
from zipfile import ZipFile

ASSETS = Path(__file__).resolve().parent
HOME = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "TingGao"
DATA = Path(os.environ["LOCALAPPDATA"]) / "TingGao"
SETTINGS = DATA / "installer.json"
VERSION = "0.3.0"
TITLE = "听稿"
MARKER = ".tinggao-install"
HRESULT = c.c_long
POINTER = c.c_void_p
ole = c.windll.ole32

def guid(identifier):
    return (c.c_ubyte * 16).from_buffer_copy(UUID(identifier).bytes_le)


def checked(result):
    if result < 0:
        raise OSError(f"Windows HRESULT 0x{result & 0xffffffff:08X}")


def call(interface, slot, result, args, *values):
    table = c.cast(interface, c.POINTER(c.POINTER(POINTER))).contents
    method = c.WINFUNCTYPE(result, POINTER, *args)(table[slot])
    return method(interface, *values)


def desktop_folder():
    pointer = c.c_wchar_p()
    checked(c.windll.shell32.SHGetKnownFolderPath(
        c.byref(guid("B4BFCC3A-DB2C-424C-B029-7FE99A87C641")), 0, None, c.byref(pointer),
    ))
    try:
        return Path(pointer.value)
    finally:
        ole.CoTaskMemFree(c.cast(pointer, POINTER))


def save_shortcut(shortcut, exe, icon):
    link = POINTER()
    persist = POINTER()
    checked(ole.CoInitializeEx(None, 2))
    try:
        clsid = guid("00021401-0000-0000-C000-000000000046")
        iid_link = guid("000214F9-0000-0000-C000-000000000046")
        iid_file = guid("0000010B-0000-0000-C000-000000000046")
        checked(ole.CoCreateInstance(c.byref(clsid), None, 1, c.byref(iid_link), c.byref(link)))
        checked(call(link, 20, HRESULT, [w.LPCWSTR], str(exe)))
        checked(call(link, 9, HRESULT, [w.LPCWSTR], str(exe.parent)))
        checked(call(link, 7, HRESULT, [w.LPCWSTR], "听稿 · 本地音视频转写"))
        checked(call(link, 17, HRESULT, [w.LPCWSTR, c.c_int], str(icon), 0))
        checked(call(link, 0, HRESULT, [POINTER, c.POINTER(POINTER)], c.byref(iid_file), c.byref(persist)))
        checked(call(persist, 6, HRESULT, [w.LPCWSTR, w.BOOL], str(shortcut), True))
    finally:
        for interface in (persist, link):
            if interface:
                call(interface, 2, w.ULONG, [])
        ole.CoUninitialize()


def owned_folder(path):
    try:
        return (
            not path.is_symlink() and not path.is_junction()
            and (path / "TingGao.exe").is_file()
            and (path / MARKER).read_text(encoding="ascii").startswith("TingGao 0.")
        )
    except (OSError, UnicodeError):
        return False


def read_settings():
    try:
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
        candidate = Path(settings["path"])
        if candidate.is_absolute() and owned_folder(candidate):
            return candidate, bool(settings.get("shortcut", True))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return HOME, True


def save_settings(target, shortcut):
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    temporary = SETTINGS.with_name(f"installer-{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps({"path": str(target), "shortcut": shortcut}), encoding="utf-8")
        temporary.replace(SETTINGS)
    finally:
        temporary.unlink(missing_ok=True)


def shortcut_target(path):
    link, persist = POINTER(), POINTER()
    checked(ole.CoInitializeEx(None, 2))
    try:
        clsid = guid("00021401-0000-0000-C000-000000000046")
        iid_link = guid("000214F9-0000-0000-C000-000000000046")
        iid_file = guid("0000010B-0000-0000-C000-000000000046")
        checked(ole.CoCreateInstance(c.byref(clsid), None, 1, c.byref(iid_link), c.byref(link)))
        checked(call(link, 0, HRESULT, [POINTER, c.POINTER(POINTER)], c.byref(iid_file), c.byref(persist)))
        checked(call(persist, 5, HRESULT, [w.LPCWSTR, w.DWORD], str(path), 0))
        result = c.create_unicode_buffer(32768)
        checked(call(link, 3, HRESULT, [w.LPWSTR, c.c_int, POINTER, w.DWORD], result, len(result), None, 4))
        return Path(result.value) if result.value else None
    except OSError:
        return None
    finally:
        for interface in (persist, link):
            if interface:
                call(interface, 2, w.ULONG, [])
        ole.CoUninitialize()


def install(target, desktop, report, *, make_shortcut=True, old_target=None):
    target = target.absolute()
    desktop = desktop.absolute()
    resolved = target.resolve()
    data = DATA.resolve()
    if resolved == Path(resolved.anchor) or resolved == data or resolved in data.parents or data in resolved.parents:
        raise ValueError("请选择独立的程序目录，不能使用根目录或稿件数据目录。")
    if target.is_symlink() or target.is_junction():
        raise ValueError("请选择实际文件夹。")
    if target.exists() and not owned_folder(target) and (not target.is_dir() or any(target.iterdir())):
        raise FileExistsError("安装目录已有其他内容。请移走该目录后再试。")
    suffix = uuid4().hex
    stage = target.with_name(".tg-new-" + suffix[:10])
    previous = target.with_name(".tg-old-" + suffix[:10])
    shortcut = desktop / (TITLE + ".lnk")
    pending_link = desktop / (TITLE + "-" + suffix + ".lnk")
    target.parent.mkdir(parents=True, exist_ok=True)
    if make_shortcut:
        desktop.mkdir(parents=True, exist_ok=True)
    prior_link = shortcut_target(shortcut) if shortcut.is_file() else None
    owned_link = prior_link in {path / "TingGao.exe" for path in (target, old_target, HOME) if path}
    if make_shortcut and shortcut.exists() and not owned_link:
        raise FileExistsError("桌面已有同名快捷方式。请重命名它，或取消创建快捷方式。")
    stage.mkdir()
    replaced = False
    try:
        report("正在解压应用和模型…")
        with ZipFile(ASSETS / "payload.zip") as archive:
            local_stage = Path("\\\\?\\" + str(stage))
            archive.extractall(local_stage)
        bundle = local_stage / "TingGao"
        if not (bundle / "TingGao.exe").is_file():
            raise ValueError("安装包内容不完整。")
        copyfile(ASSETS / "tinggao.ico", bundle / "tinggao.ico")
        (bundle / MARKER).write_text(f"TingGao {VERSION}\n", encoding="ascii")
        if target.exists():
            target.rename(previous)
        bundle.rename(target)
        replaced = True
        if make_shortcut:
            report("正在添加桌面快捷方式…")
            save_shortcut(pending_link, target / "TingGao.exe", target / "tinggao.ico")
            pending_link.replace(shortcut)
        elif owned_link:
            shortcut.unlink()
    except Exception:
        if replaced:
            rmtree(target)
        if previous.exists():
            previous.rename(target)
        raise
    finally:
        pending_link.unlink(missing_ok=True)
        rmtree(Path("\\\\?\\" + str(stage)), ignore_errors=True)
    leftover = None
    if previous.exists():
        try:
            rmtree(previous)
        except OSError:
            leftover = previous
    return target / "TingGao.exe", leftover


def show():
    root = tk.Tk()
    root.title("安装听稿")
    root.geometry("550x392")
    root.resizable(False, False)
    root.configure(background="#f8f6ff")
    root.iconbitmap(str(ASSETS / "tinggao.ico"))
    progress = SimpleQueue()
    style = ttk.Style()
    style.configure("Install.TButton", font=("Microsoft YaHei UI", 10), padding=(14, 9))
    tk.Label(root, text="安装听稿", font=("Microsoft YaHei UI", 24, "bold"),
             foreground="#242040", background="#f8f6ff").pack(anchor="w", padx=28, pady=(26, 3))
    tk.Label(root, text="选择安装位置。更新到原目录会替换旧程序。",
             font=("Microsoft YaHei UI", 10), foreground="#4f4868", background="#f8f6ff").pack(anchor="w", padx=29)
    initial, create_shortcut = read_settings()
    location = tk.StringVar(value=str(initial))
    wants_shortcut = tk.BooleanVar(value=create_shortcut)
    status = tk.StringVar(value="已有转写稿和校对记录会保留。")
    controls = tk.Frame(root, background="#f8f6ff")
    controls.pack(fill="x", padx=29, pady=(22, 0))
    tk.Label(controls, text="安装位置", background="#f8f6ff", foreground="#242040").pack(anchor="w")
    path_row = tk.Frame(controls, background="#f8f6ff")
    path_row.pack(fill="x", pady=(5, 7))
    path_box = ttk.Entry(path_row, textvariable=location, state="readonly")
    path_box.pack(side="left", fill="x", expand=True, ipady=5)

    def browse():
        parent = Path(location.get()).parent
        selected = filedialog.askdirectory(parent=root, initialdir=str(parent), title="选择安装位置")
        if selected:
            folder = Path(selected)
            location.set(str(folder if owned_folder(folder) or folder.name.lower() == "tinggao" else folder / "TingGao"))

    choose = ttk.Button(path_row, text="浏览…", command=browse)
    choose.pack(side="right", padx=(9, 0), ipady=4)
    box = ttk.Checkbutton(controls, text="创建桌面快捷方式", variable=wants_shortcut)
    box.pack(anchor="w", pady=3)
    tk.Label(root, textvariable=status, wraplength=480, justify="left", font=("Microsoft YaHei UI", 10),
             background="#f8f6ff", foreground="#4f4868").pack(anchor="w", padx=29, pady=(17, 10))
    busy = False

    def worker(target, shortcut):
        try:
            exe, leftover = install(target, desktop_folder(), lambda text: progress.put(("status", text)),
                                    make_shortcut=shortcut, old_target=initial)
            try:
                save_settings(exe.parent, shortcut)
            except OSError:
                progress.put(("done", (exe, "本次安装选项未能保存。")))
                return
            note = "安装完成。"
            if shortcut:
                note += "桌面快捷方式已创建。"
            if leftover:
                note += f" 部分旧程序文件仍被占用。旧目录：{leftover}"
            elif initial != exe.parent and owned_folder(initial):
                note += "你选择了新目录，原目录的安装仍可用。"
            progress.put(("done", (exe, note)))
        except Exception as error:
            progress.put(("error", str(error)))

    def start():
        nonlocal busy
        busy = True
        action.configure(state="disabled")
        choose.configure(state="disabled")
        box.configure(state="disabled")
        Thread(target=worker, args=(Path(location.get()), wants_shortcut.get()), daemon=True).start()

    def check():
        nonlocal busy
        try:
            kind, value = progress.get_nowait()
            if kind == "status":
                status.set(value)
            else:
                busy = False
                if kind == "done":
                    exe, message = value
                    status.set(message)
                    action.configure(text="打开听稿", state="normal", command=lambda: launch(exe))
                else:
                    status.set("安装未完成。\n" + value)
                    action.configure(state="normal")
                    choose.configure(state="normal")
                    box.configure(state="normal")
        except Empty:
            pass
        root.after(100, check)

    def launch(path):
        subprocess.Popen([str(path)], cwd=path.parent)
        root.destroy()

    def close():
        if not busy:
            root.destroy()

    action = ttk.Button(root, text="安装", command=start, style="Install.TButton")
    action.pack(anchor="w", padx=28)
    root.protocol("WM_DELETE_WINDOW", close)
    check()
    root.mainloop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--qa-target", type=Path)
    parser.add_argument("--qa-desktop", type=Path)
    parser.add_argument("--no-desktop-shortcut", action="store_true")
    args = parser.parse_args()
    if args.qa_target and args.qa_desktop:
        install(args.qa_target, args.qa_desktop, lambda _: None,
                make_shortcut=not args.no_desktop_shortcut)
    else:
        show()

