#!/bin/bash
# ===================================
# Daily Stock Analysis - 停止脚本
# ===================================
# 使用方式：./scripts/stop.sh
# ===================================

# 注意：不使用 set -e，避免进程不存在时误判退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 配置
PROJECT_NAME="daily-stock-analysis"
PID_FILE="/tmp/${PROJECT_NAME}.pid"
LOG_FILE="logs/server.log"

# 确保在项目根目录
cd "$(dirname "$0")/.." || exit 1

echo -e "${BLUE}🛑 停止 Daily Stock Analysis 服务...${NC}"
echo ""

# 方法 1：通过 PID 文件停止
STOPPED=false

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo -e "${YELLOW}→ 停止进程 (PID: $PID)...${NC}"
        kill "$PID" 2>/dev/null || true
        
        # 等待进程退出
        for i in {1..10}; do
            if ! ps -p "$PID" > /dev/null 2>&1; then
                STOPPED=true
                break
            fi
            sleep 1
        done
        
        if [ "$STOPPED" = true ]; then
            echo -e "${GREEN}✅ 服务已停止${NC}"
        else
            echo -e "${YELLOW}⚠️  进程未响应，强制停止...${NC}"
            kill -9 "$PID" 2>/dev/null || true
            echo -e "${GREEN}✅ 服务已强制停止${NC}"
        fi
    else
        echo -e "${YELLOW}⚠️  进程不存在 (PID: $PID)${NC}"
    fi
    rm -f "$PID_FILE"
fi

# 方法 2：通过进程名查找并停止（备用）
if pgrep -f "main.py.*--serve" > /dev/null 2>&1; then
    echo -e "${YELLOW}→ 查找并停止剩余进程...${NC}"
    pkill -f "main.py.*--serve" || true
    echo -e "${GREEN}✅ 服务已停止${NC}"
    STOPPED=true
fi

# 清理 PID 文件
rm -f "$PID_FILE"

# 显示最终状态
echo ""
if [ "$STOPPED" = true ]; then
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}✅ 服务已完全停止${NC}"
    echo -e "${GREEN}========================================${NC}"
else
    echo -e "${YELLOW}========================================${NC}"
    echo -e "${YELLOW}⚠️  服务未在运行${NC}"
    echo -e "${YELLOW}========================================${NC}"
fi

echo ""
echo "重新启动：./scripts/run.sh"
echo "查看状态：./scripts/run.sh --status"
echo ""
