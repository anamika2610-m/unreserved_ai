#!/bin/bash
# Build script for Unreserved API Docker/Podman image

set -e

echo "🔨 Building Unreserved API Docker image..."
echo ""

# Get the directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Check if Podman machine is running
if command -v podman &> /dev/null; then
    if podman machine list | grep -q "Currently running"; then
        # Set DOCKER_HOST for Podman compatibility
        PODMAN_SOCK=$(podman machine inspect podman-machine-default --format '{{.ConnectionInfo.PodmanSocket.Path}}' 2>/dev/null || echo "")
        if [ -n "$PODMAN_SOCK" ]; then
            export DOCKER_HOST="unix://$PODMAN_SOCK"
        else
            # Fallback to default socket location
            export DOCKER_HOST='unix:///var/folders/27/gk80mfhj1z1_0d2zmssqm3h40000gp/T/podman/podman-machine-default-api.sock'
        fi
        echo "✓ Using Podman (DOCKER_HOST=$DOCKER_HOST)"
    else
        echo "⚠️  Podman machine is not running. Starting it..."
        podman machine start podman-machine-default || {
            echo "❌ Failed to start Podman machine"
            exit 1
        }
        # Wait a moment for the machine to be ready
        sleep 2
        export DOCKER_HOST='unix:///var/folders/27/gk80mfhj1z1_0d2zmssqm3h40000gp/T/podman/podman-machine-default-api.sock'
    fi
fi

# Build the image
echo ""
echo "📦 Building image: unreserved-api:latest"
echo ""

podman build -t unreserved-api:latest -f infra/docker/Dockerfile .

echo ""
echo "✅ Build complete!"
echo ""
echo "To run the container:"
echo "  podman run -p 8000:8000 --env-file .env unreserved-api:latest"
echo ""
echo "Or use docker-compose:"
echo "  cd infra/docker && docker-compose up"

