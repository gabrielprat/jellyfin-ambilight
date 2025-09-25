#!/bin/bash

# Jellyfin Ambilight Docker Manager
# Comprehensive management script for the containerized ambilight system

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
CONTAINER_NAME="jellyfin-ambilight"
COMPOSE_FILE="docker-compose.yaml"
ENV_FILE="env.production"

# Determine environment file based on command argument
get_env_file() {
    local env_arg="$1"
    case "$env_arg" in
        development|dev)
            echo "env.development"
            ;;
        production|prod)
            echo "env.production"
            ;;
        homeserver|home)
            echo "env.homeserver"
            ;;
        nas)
            echo "env.nas"
            ;;
        remote|remote-deployment)
            echo "env.remote-deployment"
            ;;
        *)
            echo "env.production"  # default
            ;;
    esac
}

print_header() {
    echo -e "${BLUE}================================================${NC}"
    echo -e "${BLUE}  Jellyfin Ambilight Docker Manager${NC}"
    echo -e "${BLUE}================================================${NC}"
}

print_usage() {
    echo "Usage: $0 {start|stop|restart|logs|status|test|build|update|shell|cleanup|network} [environment]"
    echo ""
    echo "Commands:"
    echo "  start     - Start the ambilight service"
    echo "  stop      - Stop the ambilight service"
    echo "  restart   - Restart the ambilight service"
    echo "  logs      - Show real-time logs"
    echo "  status    - Show container status and health"
    echo "  test      - Test system connectivity and configuration"
    echo "  build     - Rebuild the Docker image (only needed once or for system updates)"
    echo "  update    - Update source code (no rebuild needed!)"
    echo "  shell     - Open shell in running container"
    echo "  cleanup   - Remove old containers and images"
    echo "  monitor   - Start with monitoring service"
    echo "  testrun   - Start test container"
    echo "  network   - Network troubleshooting and diagnostics"
    echo ""
    echo "Environment files (optional):"
    echo "  development      - Use env.development (default for local testing)"
    echo "  production       - Use env.production (default for normal start)"
    echo "  homeserver       - Use env.homeserver (for home server deployment)"
    echo "  nas              - Use env.nas (for NAS deployment)"
    echo "  remote-deployment - Use env.remote-deployment (for different machines)"
    echo ""
    echo "Examples:"
    echo "  $0 start                    # Start with production config"
    echo "  $0 start development        # Start with development config"
    echo "  $0 test homeserver          # Test home server configuration"
    echo "  $0 network                  # Troubleshoot network issues"
    echo "  $0 logs                     # Follow logs"
    echo "  $0 testrun                  # Run quick connectivity test"
    echo "  $0 monitor                  # Start with monitoring"
    echo ""
    echo "🔧 Development workflow:"
    echo "  1. Build image once:        $0 build"
    echo "  2. Edit code in any editor"
    echo "  3. Restart service:         $0 restart"
    echo "  4. No rebuild needed!       Code changes are mounted via volumes"
    echo ""
    echo "🌐 Network troubleshooting:"
    echo "  $0 network                  # Run network diagnostics"
    echo "  $0 test homeserver          # Test specific environment"
    echo "  Use env.remote-deployment   # For different machines"
}

check_requirements() {
    echo -e "${YELLOW}🔍 Checking requirements...${NC}"

    # Check Docker
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}❌ Docker is not installed${NC}"
        exit 1
    fi

    # Check Docker Compose
    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        echo -e "${RED}❌ Docker Compose is not installed${NC}"
        exit 1
    fi

    # Check environment file
    if [ ! -f "$ENV_FILE" ]; then
        echo -e "${YELLOW}⚠️  Environment file not found: $ENV_FILE${NC}"
        echo -e "${YELLOW}   Copying from example...${NC}"
        if [ -f "env.example" ]; then
            cp env.example "$ENV_FILE"
            echo -e "${GREEN}✅ Created $ENV_FILE from example${NC}"
            echo -e "${YELLOW}   Please edit $ENV_FILE with your configuration${NC}"
        else
            echo -e "${RED}❌ No environment template found${NC}"
            exit 1
        fi
    fi

    echo -e "${GREEN}✅ Requirements check passed${NC}"
}

start_service() {
    local env_arg="$1"
    local env_file=$(get_env_file "$env_arg")

    echo -e "${GREEN}🚀 Starting Jellyfin Ambilight service...${NC}"
    echo -e "${BLUE}   Environment: $env_file${NC}"

    check_requirements

    # Check if environment file exists
    if [ ! -f "$env_file" ]; then
        echo -e "${RED}❌ Environment file not found: $env_file${NC}"
        echo -e "${YELLOW}   Available files:${NC}"
        ls -1 env.* 2>/dev/null || echo "   No environment files found"
        exit 1
    fi

    # Start the service
    docker-compose --env-file "$env_file" -f "$COMPOSE_FILE" up -d

    echo -e "${GREEN}✅ Service started successfully${NC}"
    echo -e "${BLUE}   Environment: $env_file${NC}"
    echo ""
    echo "Monitor with: $0 logs"
    echo "Check status: $0 status"
}

stop_service() {
    echo -e "${YELLOW}🛑 Stopping Jellyfin Ambilight service...${NC}"

    docker-compose -f "$COMPOSE_FILE" down

    echo -e "${GREEN}✅ Service stopped${NC}"
}

restart_service() {
    echo -e "${BLUE}🔄 Restarting Jellyfin Ambilight service...${NC}"

    stop_service
    sleep 2
    start_service
}

show_logs() {
    echo -e "${BLUE}📝 Showing service logs (Ctrl+C to exit)...${NC}"

    docker-compose -f "$COMPOSE_FILE" logs -f --tail=50
}

show_status() {
    echo -e "${BLUE}📊 Service Status:${NC}"
    echo ""

    # Container status
    if docker ps --filter "name=$CONTAINER_NAME" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -q "$CONTAINER_NAME"; then
        echo -e "${GREEN}✅ Container is running:${NC}"
        docker ps --filter "name=$CONTAINER_NAME" --format "table {{.Names}}\t{{.Status}}\t{{.CreatedAt}}"
        echo ""

        # Health check
        health=$(docker inspect --format='{{.State.Health.Status}}' "$CONTAINER_NAME" 2>/dev/null || echo "unknown")
        case $health in
            "healthy")
                echo -e "${GREEN}✅ Health: Healthy${NC}"
                ;;
            "unhealthy")
                echo -e "${RED}❌ Health: Unhealthy${NC}"
                ;;
            "starting")
                echo -e "${YELLOW}⏳ Health: Starting...${NC}"
                ;;
            *)
                echo -e "${YELLOW}⚠️  Health: Unknown${NC}"
                ;;
        esac

        # Resource usage
        echo ""
        echo -e "${BLUE}💾 Resource Usage:${NC}"
        docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}" "$CONTAINER_NAME"

    else
        echo -e "${RED}❌ Container is not running${NC}"
    fi

    # Recent logs
    echo ""
    echo -e "${BLUE}📋 Recent logs (last 10 lines):${NC}"
    docker-compose -f "$COMPOSE_FILE" logs --tail=10 2>/dev/null || echo "No logs available"
}

test_system() {
    local env_arg="$1"
    local env_file=$(get_env_file "$env_arg")

    echo -e "${BLUE}🧪 Testing system configuration...${NC}"
    echo -e "${BLUE}   Environment: $env_file${NC}"

    check_requirements

    # Check if environment file exists
    if [ ! -f "$env_file" ]; then
        echo -e "${RED}❌ Environment file not found: $env_file${NC}"
        exit 1
    fi

    # Load environment
    set -a  # automatically export all variables
    source <(grep -E '^[A-Z_].*=' "$env_file")
    set +a  # stop automatically exporting

    echo ""
    echo -e "${BLUE}🔧 Configuration:${NC}"
    echo "  Jellyfin URL: $JELLYFIN_BASE_URL"
    echo "  WLED Host: $WLED_HOST:$WLED_UDP_PORT"
    echo "  Data Path: $DATA_PATH"
    echo "  Movies Path: $MOVIES_PATH"
    echo "  TV Path: $TV_PATH"

    # Test paths
    echo ""
    echo -e "${BLUE}📁 Testing paths:${NC}"

    if [ -d "$DATA_PATH" ]; then
        echo -e "${GREEN}✅ Data path exists: $DATA_PATH${NC}"
        echo "   Size: $(du -sh "$DATA_PATH" 2>/dev/null | cut -f1 || echo "Unknown")"
    else
        echo -e "${YELLOW}⚠️  Data path missing, will be created: $DATA_PATH${NC}"
        mkdir -p "$DATA_PATH" 2>/dev/null || echo -e "${RED}❌ Cannot create data path${NC}"
    fi

    if [ -d "$MOVIES_PATH" ]; then
        echo -e "${GREEN}✅ Movies path exists: $MOVIES_PATH${NC}"
        echo "   Files: $(find "$MOVIES_PATH" -name "*.mp4" -o -name "*.mkv" -o -name "*.avi" 2>/dev/null | wc -l || echo "0") video files"
    else
        echo -e "${RED}❌ Movies path missing: $MOVIES_PATH${NC}"
    fi

    if [ -d "$TV_PATH" ]; then
        echo -e "${GREEN}✅ TV path exists: $TV_PATH${NC}"
        echo "   Files: $(find "$TV_PATH" -name "*.mp4" -o -name "*.mkv" -o -name "*.avi" 2>/dev/null | wc -l || echo "0") video files"
    else
        echo -e "${RED}❌ TV path missing: $TV_PATH${NC}"
    fi

    # Test Jellyfin connectivity
    echo ""
    echo -e "${BLUE}🌐 Testing Jellyfin connectivity...${NC}"
    if command -v curl &> /dev/null; then
        response=$(curl -s -o /dev/null -w "%{http_code}" \
            -H "Authorization: MediaBrowser Client=\"docker-test\", Device=\"Docker\", DeviceId=\"test-001\", Version=\"1.0\", Token=\"$JELLYFIN_API_KEY\"" \
            "$JELLYFIN_BASE_URL/System/Info" || echo "000")

        if [ "$response" = "200" ]; then
            echo -e "${GREEN}✅ Jellyfin connectivity successful${NC}"
        else
            echo -e "${RED}❌ Jellyfin connectivity failed (HTTP $response)${NC}"
        fi
    else
        echo -e "${YELLOW}⚠️  curl not available, skipping connectivity test${NC}"
    fi

    echo ""
    echo -e "${GREEN}🎯 Test complete!${NC}"
}

build_image() {
    echo -e "${BLUE}🔨 Building Docker image...${NC}"

    docker-compose -f "$COMPOSE_FILE" build --no-cache

    echo -e "${GREEN}✅ Image built successfully${NC}"
}

update_system() {
    echo -e "${BLUE}🔄 Updating system...${NC}"
    echo -e "${YELLOW}ℹ️  With volume mounts, code updates are automatic!${NC}"
    echo -e "${YELLOW}   Just restart the service to pick up changes.${NC}"

    # Pull latest code if this is a git repository
    if [ -d ".git" ]; then
        echo "Pulling latest code..."
        git pull
    else
        echo "Not a git repository - manual code update needed"
    fi

    # Restart service to pick up changes
    echo "Restarting service..."
    restart_service

    echo -e "${GREEN}✅ Update complete (no rebuild needed!)${NC}"
}

test_run() {
    local env_arg="$1"
    local env_file=$(get_env_file "$env_arg")

    echo -e "${BLUE}🧪 Running connectivity test...${NC}"
    echo -e "${BLUE}   Environment: $env_file${NC}"

    check_requirements

    # Check if environment file exists
    if [ ! -f "$env_file" ]; then
        echo -e "${RED}❌ Environment file not found: $env_file${NC}"
        exit 1
    fi

    # Run test container
    docker-compose --env-file "$env_file" -f "$COMPOSE_FILE" --profile test run --rm jellyfin-ambilight-test

    echo -e "${GREEN}✅ Test complete${NC}"
}

open_shell() {
    echo -e "${BLUE}🐚 Opening shell in container...${NC}"

    if docker ps --filter "name=$CONTAINER_NAME" --format "{{.Names}}" | grep -q "$CONTAINER_NAME"; then
        docker exec -it "$CONTAINER_NAME" /bin/bash
    else
        echo -e "${RED}❌ Container is not running${NC}"
        echo "Start the service first: $0 start"
    fi
}

cleanup_system() {
    echo -e "${YELLOW}🧹 Cleaning up Docker resources...${NC}"

    read -p "This will remove stopped containers and unused images. Continue? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        # Remove stopped containers
        docker container prune -f

        # Remove unused images
        docker image prune -f

        # Remove unused volumes (be careful!)
        read -p "Also remove unused volumes? This may delete data! (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            docker volume prune -f
        fi

        echo -e "${GREEN}✅ Cleanup complete${NC}"
    else
        echo "Cleanup cancelled"
    fi
}

start_with_monitoring() {
    echo -e "${GREEN}🚀 Starting with monitoring service...${NC}"

    check_requirements

    # Use environment file
    set -a  # automatically export all variables
    source <(grep -E '^[A-Z_].*=' "$ENV_FILE")
    set +a  # stop automatically exporting

    # Start with monitoring profile
    docker-compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" --profile monitor up -d

    echo -e "${GREEN}✅ Service and monitoring started${NC}"
    echo ""
    echo "Monitor with: $0 logs"
    echo "Check status: $0 status"
}

network_troubleshoot() {
    echo -e "${BLUE}🌐 Running network troubleshooting...${NC}"

    if [ -f "./troubleshoot-network.sh" ]; then
        echo -e "${YELLOW}Executing network diagnostics...${NC}"
        ./troubleshoot-network.sh
    else
        echo -e "${RED}❌ troubleshoot-network.sh not found${NC}"
        echo -e "${YELLOW}Manual troubleshooting steps:${NC}"
        echo ""
        echo "1. Check DNS resolution:"
        echo "   nslookup jellyfin.galagaon.com"
        echo ""
        echo "2. Test connectivity:"
        echo "   curl -I https://jellyfin.galagaon.com"
        echo ""
        echo "3. Check if running on different network:"
        echo "   Consider using IP address instead of hostname"
        echo ""
        echo "4. Try host networking:"
        echo "   docker-compose -f docker-compose.host-network.yaml up"
    fi

    echo ""
    echo -e "${BLUE}💡 Common solutions:${NC}"
    echo "1. Update env.homeserver with IP address:"
    echo "   JELLYFIN_BASE_URL=https://192.168.1.XXX:8920"
    echo ""
    echo "2. Use public DNS:"
    echo "   DNS_SERVER=8.8.8.8"
    echo ""
    echo "3. Use host networking:"
    echo "   docker-compose -f docker-compose.host-network.yaml --env-file env.homeserver up"
}

# Main script logic
case "$1" in
    start)
        print_header
        start_service "$2"
        ;;
    stop)
        print_header
        stop_service
        ;;
    restart)
        print_header
        restart_service
        ;;
    logs)
        print_header
        show_logs
        ;;
    status)
        print_header
        show_status
        ;;
    test)
        print_header
        test_system "$2"
        ;;
    testrun)
        print_header
        test_run "$2"
        ;;
    build)
        print_header
        build_image
        ;;
    update)
        print_header
        update_system
        ;;
    shell)
        print_header
        open_shell
        ;;
    cleanup)
        print_header
        cleanup_system
        ;;
    monitor)
        print_header
        start_with_monitoring
        ;;
    network)
        print_header
        network_troubleshoot
        ;;
    *)
        print_header
        if [ -z "$1" ]; then
            echo -e "${YELLOW}ℹ️  No command specified${NC}"
        else
            echo -e "${RED}❌ Invalid command: $1${NC}"
        fi
        echo ""
        print_usage
        exit 1
        ;;
esac
