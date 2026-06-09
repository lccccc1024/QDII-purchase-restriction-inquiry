@echo off
title 基金申购监控

:: 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.8+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 安装依赖
echo 正在检查依赖...
pip install -r requirements.txt

:: 如果是命令行带参数，直接执行
if not "%1"=="" goto :run_with_args

:: ====== 交互式菜单 ======
:menu
cls
echo ==========================================
echo   场外纳指100 / 标普500 基金申购监控
echo ==========================================
echo.
echo 当前基金列表:
if exist fund_list.json (
    python -c "import json;d=json.load(open('fund_list.json','r',encoding='utf-8'));print(f'  {len(d)} 只人民币份额基金');n=sum(1 for x in d if x[\"index\"]==\"nasdaq100\");s=sum(1 for x in d if x[\"index\"]==\"sp500\");print(f'  纳斯达克100: {n} 只');print(f'  标普500: {s} 只')"
) else (
    echo   fund_list.json 不存在，首次运行需初始化
)
echo.
echo   最后报告:
if exist report.txt (
    findstr /c:"扫描时间" /c:"基金总数" /c:"状态分布" report.txt 2>nul
) else (
    echo   暂无报告
)
echo.
echo ==========================================
echo   [1] 查看最新报告
echo   [2] 立即扫描（约2分钟）
echo   [3] 重建基金列表
echo   [4] 常驻监控（每30分钟）
echo   [Q] 退出
echo ==========================================
set /p choice="请选择 [1-4/Q]: "

if "%choice%"=="1" goto :view_report
if "%choice%"=="2" goto :scan_once
if "%choice%"=="3" goto :init_list
if "%choice%"=="4" goto :daemon
if /i "%choice%"=="Q" exit /b 0
goto :menu

:view_report
cls
if exist report.txt (
    type report.txt
) else (
    echo 暂无报告，请先执行扫描 [2]。
)
echo.
pause
goto :menu

:scan_once
cls
echo 正在扫描全部基金，请稍候...
echo.
if not exist fund_list.json (
    python monitor.py --init --once --chart
) else (
    python monitor.py --once --chart
)
echo.
echo ==========================================
echo 扫描完成！报告已保存至 report.txt
echo ==========================================
pause
goto :menu

:init_list
cls
echo 正在重建基金列表...
echo.
python monitor.py --init
echo.
pause
goto :menu

:daemon
cls
echo 启动常驻监控（每30分钟扫描一次）...
echo 每次扫描后自动生成报告和图表。
echo 按 Ctrl+C 可随时停止。
echo.
python monitor.py --daemon --interval 1800 --chart
pause
goto :menu

:: ====== 命令行参数模式 ======
:run_with_args
if "%1"=="init"    python monitor.py --init
if "%1"=="once" (
    if not exist fund_list.json (
        python monitor.py --init --once --chart
    ) else (
        python monitor.py --once --chart
    )
)
if "%1"=="full"    python monitor.py --init --once --chart
if "%1"=="daemon" (
    if "%2"=="" (
        python monitor.py --daemon --interval 1800 --chart
    ) else (
        echo %2|findstr /r "^[0-9][0-9]*$" >nul
        if %errorlevel% neq 0 (
            echo [错误] 间隔参数必须为正整数，如: run.bat daemon 3600
            pause
            exit /b 1
        )
        python monitor.py --daemon --interval %2 --chart
    )
)
echo.
echo 执行完毕。
pause
