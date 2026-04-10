#!/bin/bash
# ===================================
# Daily Stock Analysis - 更新部署脚本
# ===================================
# 使用方式：./scripts/deploy-update.sh
#
# 功能：
# 1. 拉取最新代码
# 2. 重新构建 Docker 镜像
# 3. 重启服务
# ===================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}🚀 开始更新部署 Daily Stock Analysis${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# 确保在项目根目录
cd "$(dirname "$0")/.." || exit 1

# 1. 拉取最新代码
echo -e "${YELLOW}📥 拉取最新代码...${NC}"
git pull origin main
echo ""

# 2. 停止旧服务
echo -e "${YELLOW}🛑 停止旧服务...${NC}"
docker-compose -f docker/docker-compose.yml down
echo ""

# 3. 重新构建镜像
echo -e "${YELLOW}🔨 重新构建 Docker 镜像...${NC}"
docker-compose -f docker/docker-compose.yml build
echo ""

# 4. 启动新服务
echo -e "${YELLOW}🚀 启动新服务...${NC}"
docker-compose -f docker/docker-compose.yml up -d server
echo ""

# 等待服务启动
sleep 3

# 5. 检查状态
echo -e "${BLUE}📊 服务状态${NC}"
docker-compose -f docker/docker-compose.yml ps
echo ""

# 6. 检查健康状态
echo -e "${BLUE}🏥 健康检查...${NC}"
if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
    echo -e "${GREEN}✅ 服务运行正常${NC}"
    curl -s http://localhost:8000/api/health
    echo ""
else
    echo -e "${YELLOW}⚠️  服务可能正在启动，请稍后检查${NC}"
    echo "查看日志：docker-compose logs -f server"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✅ 更新部署完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "常用命令："
echo "  查看日志：docker-compose logs -f server"
echo "  查看状态：docker-compose ps"
echo "  停止服务：docker-compose down"
echo ""
