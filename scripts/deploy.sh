#!/bin/bash
# ===================================
# Daily Stock Analysis - 一键部署脚本
# ===================================
# 使用方式：
#   ./scripts/deploy.sh           虚拟环境部署（默认）
#   ./scripts/deploy.sh --docker  Docker 部署
# ===================================

set -e  # 遇到错误立即退出

# 部署模式
DEPLOY_MODE="venv"  # 默认：venv | docker

# 解析参数
for arg in "$@"; do
    case $arg in
        --docker|-d)
            DEPLOY_MODE="docker"
            shift
            ;;
        --help|-h)
            echo "使用方式：./scripts/deploy.sh [选项]"
            echo ""
            echo "选项："
            echo "  --docker, -d    使用 Docker 部署"
            echo "  --help, -h      显示帮助"
            echo ""
            echo "默认使用虚拟环境部署"
            exit 0
            ;;
    esac
done

echo "🚀 开始部署 Daily Stock Analysis (模式：$DEPLOY_MODE)..."

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 检查是否在正确的项目目录
if [ ! -f "main.py" ]; then
    echo -e "${RED}❌ 错误：请在项目根目录运行此脚本${NC}"
    exit 1
fi

# ===================================
# Docker 部署模式
# ===================================
if [ "$DEPLOY_MODE" = "docker" ]; then
    echo -e "${BLUE}🐳 Docker 部署模式${NC}"
    echo ""
    
    # 检查 Docker
    if ! command -v docker > /dev/null 2>&1; then
        echo -e "${RED}❌ Docker 未安装，请先安装 Docker${NC}"
        exit 1
    fi
    
    # 检查 Docker Compose
    if ! docker compose version > /dev/null 2>&1; then
        echo -e "${RED}❌ Docker Compose 未安装${NC}"
        exit 1
    fi
    
    # 检查 .env 文件
    if [ ! -f ".env" ]; then
        echo -e "${YELLOW}📝 创建 .env 配置文件...${NC}"
        cp .env.example .env
        echo -e "${GREEN}✅ .env 文件已创建${NC}"
        echo -e "${YELLOW}⚠️  请编辑 .env 填入你的配置后再次运行${NC}"
        echo ""
        echo "必须配置："
        echo "  - OPENAI_API_KEY"
        echo "  - OPENAI_BASE_URL"
        echo "  - MARKET_REVIEW_REGION"
        echo "  - CORS_ALLOW_ALL=false"
        echo ""
        exit 0
    else
        echo -e "${GREEN}✅ .env 文件已存在${NC}"
    fi
    
    # 创建数据目录
    echo -e "${YELLOW}📁 创建数据目录...${NC}"
    mkdir -p data logs reports
    
    # 构建镜像
    echo -e "${YELLOW}🔨 构建 Docker 镜像...${NC}"
    docker compose -f docker/docker-compose.yml build
    
    # 启动服务
    echo -e "${YELLOW}🚀 启动服务...${NC}"
    docker compose -f docker/docker-compose.yml up -d server
    
    # 等待启动
    sleep 3
    
    # 检查状态
    echo -e "${BLUE}📊 服务状态${NC}"
    docker compose ps
    
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}✅ Docker 部署完成！${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo "常用命令："
    echo "  查看日志：docker compose logs -f server"
    echo "  停止服务：docker compose down"
    echo "  重启服务：docker compose restart server"
    echo "  更新服务：docker compose pull && docker compose up -d"
    echo ""
    exit 0
fi

# ===================================
# 虚拟环境部署模式（默认）
# ===================================
echo -e "${BLUE}📦 虚拟环境部署模式${NC}"
echo ""

# 1. 检查 Python 版本
echo -e "${YELLOW}📦 检查 Python 环境...${NC}"
python3 --version || {
    echo -e "${RED}❌ Python3 未安装，请先安装 Python 3.11+${NC}"
    exit 1
}

# 2. 创建虚拟环境（如果不存在）
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}📦 创建虚拟环境...${NC}"
    python3 -m venv venv
fi

# 3. 激活虚拟环境
echo -e "${YELLOW}🔧 激活虚拟环境...${NC}"
source venv/bin/activate

# 4. 安装 Python 依赖
echo -e "${YELLOW}📦 安装 Python 依赖...${NC}"
pip install --upgrade pip
pip install -r requirements.txt

# 5. 安装前端依赖（如果存在）
if [ -d "apps/dsa-web" ] && [ -f "apps/dsa-web/package.json" ]; then
    echo -e "${YELLOW}📦 安装前端依赖...${NC}"
    cd apps/dsa-web
    npm install
    npm run build
    cd ../..
fi

# 6. 创建 .env 文件（如果不存在）
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}📝 创建 .env 配置文件...${NC}"
    cp .env.example .env
    echo -e "${GREEN}✅ .env 文件已创建，请编辑后填入你的配置${NC}"
    echo -e "${YELLOW}⚠️  必须配置的项目：${NC}"
    echo "   - OPENAI_API_KEY (阿里百炼 API Key)"
    echo "   - OPENAI_BASE_URL (https://coding.dashscope.aliyuncs.com/v1)"
    echo "   - MARKET_REVIEW_REGION (both/cn/us)"
    echo "   - CORS_ALLOW_ALL (生产环境设为 false)"
    echo ""
    echo "使用 nano .env 编辑配置"
else
    echo -e "${GREEN}✅ .env 文件已存在${NC}"
fi

# 7. 创建必要的数据目录
echo -e "${YELLOW}📁 创建数据目录...${NC}"
mkdir -p data logs reports

# 8. 设置权限
chmod 755 scripts/run.sh scripts/stop.sh 2>/dev/null || true

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✅ 虚拟环境部署完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "下一步操作："
echo "1. 编辑 .env 文件：nano .env"
echo "2. 运行服务：./scripts/run.sh"
echo "3. 停止服务：./scripts/stop.sh"
echo ""
echo -e "${YELLOW}⚠️  安全提醒：${NC}"
echo "   - 生产环境务必设置 CORS_ALLOW_ALL=false"
echo "   - 重新生成 API Key，不要使用开发环境的 Key"
echo "   - 配置 EC2 安全组，只开放必要端口"
echo ""
echo -e "${YELLOW}💡 提示：下次可用 Docker 部署：./scripts/deploy.sh --docker${NC}"
echo ""
