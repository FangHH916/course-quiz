@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 正在创建本地 Python 环境...
  python -m venv .venv
  if errorlevel 1 goto :failed
)
".venv\Scripts\python.exe" -c "import pypdf" >nul 2>&1
if errorlevel 1 (
  echo 正在安装 PDF 读取依赖，首次启动需要联网...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :failed
)
echo.
echo 请打开 http://127.0.0.1:8767
echo 使用期间请保留此窗口，按 Ctrl+C 关闭服务。
".venv\Scripts\python.exe" server.py
if errorlevel 1 goto :failed
exit /b 0
:failed
echo.
echo 启动失败。请确认已安装 Python 3.11 或更高版本、网络可用、8767 端口未被占用。
pause
exit /b 1
