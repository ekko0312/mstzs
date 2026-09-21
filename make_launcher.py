# -*- coding: utf-8 -*-
"""在桌面放置一个可直接双击的启动器（.bat）。

为什么不用 .lnk：
  Windows 的 IShellLink 对 .lnk 二进制结构非常挑剔（实测手写结构会被
  IPersistFile::Load 以 E_FAIL 拒绝），而生成 .lnk 的正规途径
  （WScript.Shell / cscript / COM）在本机安全策略下全部被拦截。
  .bat 是纯文本，双击即由 cmd 执行，无任何格式风险。

同时提供一个文件夹内的 start.bat 作为真正的工作脚本，桌面这份只做转发，
这样即使移动项目目录，也只需改桌面这份的一个变量。
"""
import sys
from pathlib import Path
import winreg
import os

sys.stdout.reconfigure(encoding="utf-8")

APP_DIR = Path(__file__).resolve().parent
ICON = APP_DIR / "icon.ico"
NAME = "面试题背题助手.bat"

BOM = b"\xef\xbb\xbf"


def desktop_dir() -> Path:
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        val, _ = winreg.QueryValueEx(key, "Desktop")
        winreg.CloseKey(key)
        p = Path(os.path.expandvars(val))
        if p.exists():
            return p
    except Exception:
        pass
    return Path(os.path.expanduser("~")) / "Desktop"


CONTENT = f"""@echo off
chcp 65001 >nul
title 面试题背题助手 - 启动器

rem ============================================================
rem  面试题背题助手  桌面启动器
rem  双击本文件即可启动服务并自动打开浏览器
rem ============================================================

set "APP_DIR={APP_DIR}"

if not exist "%APP_DIR%\\start.bat" (
  echo.
  echo   [错误] 找不到程序目录：
  echo   %APP_DIR%
  echo.
  echo   如果项目挪了位置，请编辑本文件，把 APP_DIR 改成新的路径。
  echo.
  pause
  exit /b 1
)

cd /d "%APP_DIR%"
call "%APP_DIR%\\start.bat"
"""

desk = desktop_dir()
out = desk / NAME

# 写 UTF-8 BOM + CRLF，保证 cmd 正确解析中文
text = CONTENT.replace("\r\n", "\n").replace("\n", "\r\n")
out.write_bytes(BOM + text.encode("utf-8"))

chk = out.read_bytes()
lf_only = chk.count(b"\n") - chk.count(b"\r\n")
print(f"桌面目录   : {desk}")
print(f"启动器     : {out}")
print(f"大小       : {len(chk)} bytes")
print(f"UTF-8 BOM  : {chk[:3] == BOM}")
print(f"裸 LF      : {lf_only}")
print(f"指向目录   : {APP_DIR}")
print(f"目标 start.bat 存在 : {(APP_DIR / 'start.bat').exists()}")
print(f"图标文件存在        : {ICON.exists()}")
print(f"\n创建成功 : {out.exists()}")
