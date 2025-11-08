#!/bin/bash
#
# Datang Reader - Docker Deployment Script
#
# This script deploys the Datang Reader application in Docker
# with the split architecture (host input client + containerized app)
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}  Datang Reader - Docker Deployment${NC}"
echo -e "${BLUE}============================================${NC}"
echo

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo -e "${RED}ERROR: Docker is not installed${NC}"
    echo "Please install Docker first: https://docs.docker.com/get-docker/"
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo -e "${RED}ERROR: Docker Compose is not installed${NC}"
    echo "Please install Docker Compose: https://docs.docker.com/compose/install/"
    exit 1
fi

# Prefer 'docker compose' over 'docker-compose'
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

echo -e "${GREEN}✓${NC} Docker is installed"
echo

# Check for .env file
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}⚠ .env file not found${NC}"
    echo "Creating .env from .env.example..."

    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo -e "${GREEN}✓${NC} Created .env file"
        echo -e "${YELLOW}⚠ IMPORTANT: Edit .env and configure your credentials!${NC}"
        echo
        read -p "Press Enter to continue after editing .env (or Ctrl+C to exit)..."
    else
        echo -e "${RED}ERROR: .env.example not found${NC}"
        exit 1
    fi
fi

echo -e "${GREEN}✓${NC} .env file exists"
echo

# Create persistent data directories
echo "Creating persistent data directories..."
mkdir -p docker-data/logs
chmod 755 docker-data

# Create empty files for volume mounts (if they don't exist)
touch docker-data/token 2>/dev/null || true
touch docker-data/queue.db 2>/dev/null || true

echo -e "${GREEN}✓${NC} Data directories created"
echo

# Build Docker image
echo "Building Docker image..."
$COMPOSE_CMD build

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Docker image built successfully"
else
    echo -e "${RED}ERROR: Docker build failed${NC}"
    exit 1
fi

echo

# Start container
echo "Starting Docker container..."
$COMPOSE_CMD up -d

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Container started"
else
    echo -e "${RED}ERROR: Failed to start container${NC}"
    exit 1
fi

echo

# Wait for container to be healthy
echo "Waiting for container to be healthy..."
sleep 3

# Check health
HEALTH_STATUS=$($COMPOSE_CMD ps | grep datang-reader | awk '{print $NF}')

if [ -z "$HEALTH_STATUS" ]; then
    echo -e "${YELLOW}⚠${NC} Could not determine health status"
else
    echo -e "${GREEN}✓${NC} Container is running"
fi

echo

# Show container status
echo "Container status:"
$COMPOSE_CMD ps

echo
echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}  Deployment Complete!${NC}"
echo -e "${BLUE}============================================${NC}"
echo
echo "Next steps:"
echo
echo "1. Test the HTTP server endpoint:"
echo -e "   ${GREEN}curl http://localhost:8080/health${NC}"
echo
echo "2. Start the input client (on host) to capture RFID scans:"
echo -e "   ${GREEN}python3 input_client.py${NC}"
echo
echo "3. Install input client as systemd service (optional):"
echo -e "   ${GREEN}sudo cp systemd/input-client.service /etc/systemd/system/${NC}"
echo -e "   ${GREEN}sudo systemctl daemon-reload${NC}"
echo -e "   ${GREEN}sudo systemctl start input-client${NC}"
echo -e "   ${GREEN}sudo systemctl enable input-client${NC}"
echo
echo "Useful commands:"
echo -e "  View logs:        ${GREEN}$COMPOSE_CMD logs -f${NC}"
echo -e "  Stop container:   ${GREEN}$COMPOSE_CMD down${NC}"
echo -e "  Restart:          ${GREEN}$COMPOSE_CMD restart${NC}"
echo -e "  Manual sync:      ${GREEN}curl -X POST http://localhost:8080/sync${NC}"
echo
