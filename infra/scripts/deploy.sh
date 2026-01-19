#!/bin/bash
# Deployment script for building and running Unreserved API with Podman/Docker

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Detect container runtime (Podman or Docker)
if command -v podman &> /dev/null; then
    CONTAINER_CMD="podman"
    echo -e "${GREEN}✓ Using Podman${NC}"
elif command -v docker &> /dev/null; then
    CONTAINER_CMD="docker"
    echo -e "${GREEN}✓ Using Docker${NC}"
else
    echo -e "${RED}❌ Neither Podman nor Docker is installed!${NC}"
    exit 1
fi

# Configuration
IMAGE_NAME="unreserved-api"
IMAGE_TAG="${IMAGE_TAG:-latest}"
CONTAINER_NAME="unreserved-api"
PORT="${PORT:-8000}"

# Function to build image
build_image() {
    echo -e "\n${YELLOW}📦 Building container image...${NC}"
    $CONTAINER_CMD build -t ${IMAGE_NAME}:${IMAGE_TAG} -f infra/docker/Dockerfile .
    echo -e "${GREEN}✓ Image built successfully${NC}"
}

# Function to stop and remove existing container
cleanup_container() {
    if $CONTAINER_CMD ps -a --format "{{.Names}}" | grep -q "^${CONTAINER_NAME}$"; then
        echo -e "\n${YELLOW}🛑 Stopping existing container...${NC}"
        $CONTAINER_CMD stop ${CONTAINER_NAME} || true
        $CONTAINER_CMD rm ${CONTAINER_NAME} || true
        echo -e "${GREEN}✓ Container cleaned up${NC}"
    fi
}

# Function to run container
run_container() {
    echo -e "\n${YELLOW}🚀 Starting container...${NC}"
    
    # Check for .env file
    ENV_FILE=""
    if [ -f ".env" ]; then
        ENV_FILE="--env-file .env"
        echo -e "${GREEN}✓ Using .env file${NC}"
    else
        echo -e "${YELLOW}⚠️  No .env file found. Set environment variables manually.${NC}"
    fi
    
    # Create chroma_db directory if it doesn't exist
    mkdir -p chroma_db
    
    # Run container
    $CONTAINER_CMD run -d \
        --name ${CONTAINER_NAME} \
        -p ${PORT}:8000 \
        ${ENV_FILE} \
        -v "$(pwd)/chroma_db:/app/chroma_db" \
        -v "$(pwd)/app/knowledge_base:/app/app/knowledge_base:ro" \
        --restart unless-stopped \
        ${IMAGE_NAME}:${IMAGE_TAG}
    
    echo -e "${GREEN}✓ Container started successfully${NC}"
    echo -e "\n${GREEN}📖 API Documentation: http://localhost:${PORT}/docs${NC}"
    echo -e "${GREEN}🔄 ReDoc: http://localhost:${PORT}/redoc${NC}"
    echo -e "\n${YELLOW}View logs: ${CONTAINER_CMD} logs -f ${CONTAINER_NAME}${NC}"
}

# Function to show usage
show_usage() {
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  build    - Build the container image"
    echo "  run      - Build and run the container"
    echo "  stop     - Stop the running container"
    echo "  logs     - Show container logs"
    echo "  shell    - Open a shell in the container"
    echo "  clean    - Remove container and image"
    echo "  help     - Show this help message"
    echo ""
    echo "Environment variables:"
    echo "  PORT           - Port to expose (default: 8000)"
    echo "  IMAGE_TAG      - Image tag (default: latest)"
    echo "  GROQ_API_KEY   - Required for LLM functionality"
    echo ""
}

# Main script logic
case "${1:-run}" in
    build)
        build_image
        ;;
    run)
        build_image
        cleanup_container
        run_container
        ;;
    stop)
        echo -e "\n${YELLOW}🛑 Stopping container...${NC}"
        $CONTAINER_CMD stop ${CONTAINER_NAME} || true
        echo -e "${GREEN}✓ Container stopped${NC}"
        ;;
    logs)
        $CONTAINER_CMD logs -f ${CONTAINER_NAME}
        ;;
    shell)
        $CONTAINER_CMD exec -it ${CONTAINER_NAME} /bin/bash
        ;;
    clean)
        echo -e "\n${YELLOW}🧹 Cleaning up...${NC}"
        $CONTAINER_CMD stop ${CONTAINER_NAME} || true
        $CONTAINER_CMD rm ${CONTAINER_NAME} || true
        $CONTAINER_CMD rmi ${IMAGE_NAME}:${IMAGE_TAG} || true
        echo -e "${GREEN}✓ Cleanup complete${NC}"
        ;;
    help|--help|-h)
        show_usage
        ;;
    *)
        echo -e "${RED}❌ Unknown command: $1${NC}"
        show_usage
        exit 1
        ;;
esac

