#!/bin/bash
#
# Datang Reader - Tailscale Serve Setup
#
# Exposes the Datang Reader HTTP server as a Tailscale service,
# making it accessible via HTTPS on your tailnet using MagicDNS.
#
# Prerequisites:
#   - Tailscale installed and logged in on this machine
#   - Datang Reader server running (Docker or native) on the configured port
#
# Usage:
#   ./tailscale-serve-setup.sh          # Setup with default port (8081)
#   ./tailscale-serve-setup.sh 8080     # Setup with custom port
#   ./tailscale-serve-setup.sh --remove # Remove the serve configuration
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Default port (host port where Docker container is mapped)
PORT="${1:-8081}"

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}  Datang Reader - Tailscale Serve Setup${NC}"
echo -e "${BLUE}============================================${NC}"
echo

# Handle --remove flag
if [ "$1" = "--remove" ]; then
    echo "Removing Tailscale serve configuration..."
    tailscale serve --remove / 2>/dev/null || true
    echo -e "${GREEN}✓${NC} Tailscale serve configuration removed"
    echo
    echo "The service is no longer exposed on your tailnet."
    exit 0
fi

# Check if Tailscale is installed
if ! command -v tailscale &> /dev/null; then
    echo -e "${RED}ERROR: Tailscale is not installed${NC}"
    echo "Install Tailscale: https://tailscale.com/download"
    exit 1
fi
echo -e "${GREEN}✓${NC} Tailscale is installed"

# Check if Tailscale is connected
TS_STATUS=$(tailscale status --json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('BackendState',''))" 2>/dev/null || echo "")
if [ "$TS_STATUS" != "Running" ]; then
    echo -e "${RED}ERROR: Tailscale is not connected${NC}"
    echo "Run: sudo tailscale up"
    exit 1
fi
echo -e "${GREEN}✓${NC} Tailscale is connected"

# Get Tailscale hostname and IP
TS_HOSTNAME=$(tailscale status --json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['Self']['DNSName'].rstrip('.'))" 2>/dev/null || echo "unknown")
TS_IP=$(tailscale ip -4 2>/dev/null || echo "unknown")

echo -e "${GREEN}✓${NC} Tailscale hostname: ${BLUE}${TS_HOSTNAME}${NC}"
echo -e "${GREEN}✓${NC} Tailscale IP: ${BLUE}${TS_IP}${NC}"
echo

# Check if the local service is running
echo "Checking if Datang Reader is running on port ${PORT}..."
if curl -sf "http://localhost:${PORT}/health" > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Datang Reader is responding on port ${PORT}"
else
    echo -e "${YELLOW}⚠${NC} Datang Reader is not responding on port ${PORT}"
    echo "  Make sure the Docker container is running and mapped to port ${PORT}"
    echo "  Continuing with setup anyway..."
fi
echo

# Configure Tailscale Serve
echo "Configuring Tailscale Serve..."
echo "  Proxying https://${TS_HOSTNAME} -> http://localhost:${PORT}"
echo

# Set up tailscale serve to proxy HTTPS traffic to the local HTTP server
# --bg runs it in the background and persists across reboots
tailscale serve --bg --https=443 "http://localhost:${PORT}"

echo
echo -e "${GREEN}✓${NC} Tailscale Serve configured successfully!"
echo
echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}  Service is now accessible on your tailnet${NC}"
echo -e "${BLUE}============================================${NC}"
echo
echo "Your Datang Reader is now available at:"
echo -e "  ${GREEN}https://${TS_HOSTNAME}${NC}"
echo
echo "Test it from any device on your tailnet:"
echo -e "  ${GREEN}curl https://${TS_HOSTNAME}/health${NC}"
echo
echo "Useful commands:"
echo -e "  View serve status:  ${GREEN}tailscale serve status${NC}"
echo -e "  Remove serve:       ${GREEN}$0 --remove${NC}"
echo -e "  Tailscale status:   ${GREEN}tailscale status${NC}"
echo
