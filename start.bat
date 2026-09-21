@echo off
chcp 65001 >nul
title 面试题背题助手
cd /d "%~dp0"

echo.
echo   ==========================================
echo      面试题背题助手  正在启动 ...
echo   ==========================================
echo.

if not exist ".venv\Scripts\python.exe" goto :no_venv

if not exist ".env" (
  echo   [提示] 未找到 .env，将以离线粗判模式运行。
  echo         建议复制 .env.example 为 .env 并填入 API Key。
  echo.
)

rem ---- 服务已在运行：直接开浏览器 ----
netstat -ano | findstr ":8501" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 goto :already

echo   服务地址：http://localhost:8501
echo   首次打开需等 5-10 秒，浏览器会自动弹出。
echo   关闭这个黑窗口即可停止服务。
echo.

rem ---- 后台延时开浏览器（用 ping 代替 timeout，兼容性更好）----
start "" /b cmd /c "ping -n 7 127.0.0.1 >nul & explorer http://localhost:8501"

".venv\Scripts\python.exe" -m streamlit run app.py --server.port 8501 --server.headless true
goto :done

:already
echo   检测到服务已在运行，直接打开浏览器 ...
start "" "http://localhost:8501"
goto :done

:no_venv
echo   [错误] 找不到虚拟环境 .venv
echo.
echo   当前目录：%CD%
echo   请确认这个脚本和 .venv 在同一个文件夹里。
echo.

:done
echo.
echo   服务已停止。按任意键关闭窗口。
pause >nul
exit /b 0
