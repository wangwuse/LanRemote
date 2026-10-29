@echo off
chcp 65001 >nul 2>&1
setlocal
cd /d "%~dp0"

echo ============================================================
echo   LanRemote v0.1  -  局域网遥控面板
echo ============================================================
echo.

rem ---- 查找 Python：优先 py 启动器，其次 python，最后常见安装路径 ----
set "PY="

where py >nul 2>&1
if not errorlevel 1 (
    py -3 -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PY=py -3"
)

if not defined PY (
    where python >nul 2>&1
    if not errorlevel 1 (
        rem 跳过 Microsoft Store 的空壳 python（运行会弹应用商店）
        python -c "import sys; print(sys.version)" >nul 2>&1
        if not errorlevel 1 set "PY=python"
    )
)

if not defined PY (
    for %%D in (
        "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
        "C:\Python313\python.exe"
        "C:\Python312\python.exe"
        "C:\Python311\python.exe"
        "C:\Python310\python.exe"
        "C:\Python39\python.exe"
    ) do (
        if not defined PY if exist %%D set "PY=%%~D"
    )
)

if not defined PY (
    echo [错误] 没有找到 Python 3。
    echo.
    echo   请先安装 Python 3.8 或更高版本： https://www.python.org/downloads/
    echo   安装时务必勾选 "Add Python to PATH"。
    echo.
    echo   LanRemote 只需要标准库，装好 Python 后无需 pip install。
    echo.
    pause
    exit /b 1
)

echo [信息] 使用 Python：%PY%
%PY% -c "import sys; print('[信息] 版本：' + sys.version.split()[0])"
echo.
echo [信息] 正在启动服务，按 Ctrl+C 可停止。
echo.

%PY% "%~dp0lanremote.py"

set "EXITCODE=%ERRORLEVEL%"
echo.
if not "%EXITCODE%"=="0" (
    echo [错误] 服务异常退出，代码 %EXITCODE%。请把上面的报错信息反馈给作者。
) else (
    echo [信息] 服务已停止。
)
pause
exit /b %EXITCODE%
