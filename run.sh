#!/usr/bin/env bash
set -e

echo "========================================"
echo "  场外纳指100 / 标普500 基金申购监控"
echo "========================================"
echo ""

# 检查 Python
if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
    echo "[错误] 未找到 Python，请先安装 Python 3.8+"
    exit 1
fi
PYTHON=$(command -v python3 || command -v python)

echo "[1/2] 检查依赖..."
$PYTHON -m pip install -r "$(dirname "$0")/requirements.txt"
echo "      依赖就绪。"

echo "[2/2] 启动监控..."
echo ""

MODE="${1:-once}"

case "$MODE" in
    init)
        $PYTHON "$(dirname "$0")/monitor.py" --init
        ;;
    once)
        if [ ! -f "$(dirname "$0")/fund_list.json" ]; then
            $PYTHON "$(dirname "$0")/monitor.py" --init --once --chart
        else
            $PYTHON "$(dirname "$0")/monitor.py" --once --chart
        fi
        ;;
    full)
        $PYTHON "$(dirname "$0")/monitor.py" --init --once --chart
        ;;
    daemon)
        INTERVAL="${2:-1800}"
        $PYTHON "$(dirname "$0")/monitor.py" --daemon --interval "$INTERVAL" --chart
        ;;
    *)
        echo "用法:"
        echo "  ./run.sh             默认：单次扫描"
        echo "  ./run.sh init        仅重建基金列表"
        echo "  ./run.sh once        单次扫描"
        echo "  ./run.sh full        重建列表 + 单次扫描"
        echo "  ./run.sh daemon [秒]  常驻监控（默认30分钟）"
        ;;
esac
