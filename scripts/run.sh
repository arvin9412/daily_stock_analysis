#!/bin/bash
# ===================================
# Daily Stock Analysis - 运行脚本
# ===================================
# 使用方式：./scripts/run.sh [选项]
#
# 选项：
#   --daemon    后台运行（默认）
#   --foreground 前台运行（调试用）
#   --docker    使用 Docker 运行
#   --status    查看运行状态
#   --logs      查看日志
#   --restart   重启服务
# ===================================

# 注意：不使用 set -e，因为 get_status 等函数会故意返回非 0 值

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
HOST="${WEBUI_HOST:-0.0.0.0}"
PORT="${API_PORT:-8000}"

# 确保在项目根目录
cd "$(dirname "$0")/.." || exit 1

# 确保日志目录存在
mkdir -p logs

# 函数：检查 .env 文件
check_env() {
    if [ ! -f ".env" ]; then
        echo -e "${RED}❌ 错误：.env 文件不存在${NC}"
        echo "请先运行：./scripts/deploy.sh"
        exit 1
    fi
}

# 函数：检查虚拟环境
check_venv() {
    if [ ! -d "venv" ]; then
        echo -e "${RED}❌ 错误：虚拟环境不存在${NC}"
        echo "请先运行：./scripts/deploy.sh"
        exit 1
    fi
}

# 函数：获取进程状态
get_status() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "running"
            return 0
        fi
    fi
    
    # 备用：通过进程名查找
    if pgrep -f "main.py.*--serve" > /dev/null 2>&1; then
        echo "running"
        return 0
    fi
    
    echo "stopped"
    return 0  # 返回 0 避免触发错误
}

# 函数：启动服务（前台）
start_foreground() {
    echo -e "${BLUE}🚀 前台启动服务...${NC}"
    source venv/bin/activate
    python main.py --serve-only --host "$HOST" --port "$PORT"
}

# 函数：启动服务（后台）
start_daemon() {
    echo -e "${BLUE}🚀 后台启动服务...${NC}"
    
    # 检查是否已在运行
    if [ "$(get_status)" = "running" ]; then
        echo -e "${YELLOW}⚠️  服务已在运行${NC}"
        echo "停止：./scripts/stop.sh"
        echo "重启：./scripts/run.sh --restart"
        exit 0
    fi
    
    source venv/bin/activate
    
    # 后台运行
    nohup python main.py --serve-only --host "$HOST" --port "$PORT" > "$LOG_FILE" 2>&1 &
    PID=$!
    echo "$PID" > "$PID_FILE"
    
    sleep 2
    
    # 检查是否启动成功
    if ps -p "$PID" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ 服务已启动 (PID: $PID)${NC}"
        echo "日志：tail -f $LOG_FILE"
        echo "停止：./scripts/stop.sh"
    else
        echo -e "${RED}❌ 服务启动失败，请查看日志：$LOG_FILE${NC}"
        exit 1
    fi
}

# 函数：停止服务
stop_service() {
    echo -e "${YELLOW}🛑 停止服务...${NC}"
    
    # 通过 PID 文件停止
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            kill "$PID" 2>/dev/null || true
            sleep 1
            echo -e "${GREEN}✅ 服务已停止 (PID: $PID)${NC}"
        else
            echo -e "${YELLOW}⚠️  服务未运行${NC}"
        fi
        rm -f "$PID_FILE"
    fi
    
    # 备用：通过进程名停止
    if pgrep -f "main.py.*--serve" > /dev/null 2>&1; then
        pkill -f "main.py.*--serve" || true
        echo -e "${GREEN}✅ 服务已停止${NC}"
    fi
}

# 函数：重启服务
restart_service() {
    echo -e "${YELLOW}🔄 重启服务...${NC}"
    stop_service
    sleep 2
    start_daemon
}

# 函数：查看日志
view_logs() {
    if [ -f "$LOG_FILE" ]; then
        tail -f "$LOG_FILE"
    else
        echo -e "${YELLOW}⚠️  日志文件不存在${NC}"
    fi
}

# 函数：显示状态
show_status() {
    echo -e "${BLUE}📊 服务状态${NC}"
    echo "================================"
    
    if [ "$(get_status)" = "running" ]; then
        echo -e "状态：${GREEN}运行中${NC}"
        
        if [ -f "$PID_FILE" ]; then
            echo "PID: $(cat "$PID_FILE")"
        fi
        
        # 检查端口
        if command -v netstat > /dev/null 2>&1; then
            PORT_STATUS=$(netstat -tlnp 2>/dev/null | grep ":$PORT " || true)
            if [ -n "$PORT_STATUS" ]; then
                echo "端口：$PORT (已监听)"
            else
                echo "端口：$PORT (未监听)"
            fi
        fi
        
        echo "日志：$LOG_FILE"
    else
        echo -e "状态：${RED}已停止${NC}"
    fi
    
    echo "================================"
}

# 主逻辑
case "${1:---daemon}" in
    --daemon|-d)
        check_env
        check_venv
        start_daemon
        ;;
    --foreground|-f)
        check_env
        check_venv
        start_foreground
        ;;
    --docker)
        echo -e "${BLUE}🐳 使用 Docker 启动...${NC}"
        if [ -f "docker/docker-compose.yml" ]; then
            # 尝试新命令 (docker compose)，失败则用旧命令 (docker-compose)
            if command -v docker > /dev/null 2>&1; then
                docker compose -f docker/docker-compose.yml up -d server || \
                docker-compose -f docker/docker-compose.yml up -d server
            else
                echo -e "${RED}❌ Docker 未安装${NC}"
                exit 1
            fi
        else
            echo -e "${RED}❌ Docker Compose 文件不存在${NC}"
            exit 1
        fi
        ;;
    --stop)
        stop_service
        ;;
    --restart)
        check_env
        check_venv
        restart_service
        ;;
    --status|-s)
        show_status
        ;;
    --logs|-l)
        view_logs
        ;;
    --help|-h)
        echo "使用方式：./scripts/run.sh [选项]"
        echo ""
        echo "选项："
        echo "  --daemon, -d      后台运行（默认）"
        echo "  --foreground, -f  前台运行（调试用）"
        echo "  --docker          使用 Docker 运行"
        echo "  --stop            停止服务"
        echo "  --restart         重启服务"
        echo "  --status, -s      查看运行状态"
        echo "  --logs, -l        查看日志"
        echo "  --help, -h        显示帮助"
        ;;
    *)
        echo -e "${RED}❌ 未知选项：$1${NC}"
        echo "使用 ./scripts/run.sh --help 查看帮助"
        exit 1
        ;;
esac
