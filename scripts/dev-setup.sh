#!/bin/bash
set -e

echo "🚀 Setting up Astra MCP development environment..."

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "❌ uv is not installed. Please install it first:"
    echo "   curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

echo "✅ Found uv"

# Install root dependencies
echo "📦 Installing root dependencies..."
uv sync --all-extras

# Install common library dependencies
echo "📦 Installing common library dependencies..."
cd common
uv sync --all-extras
cd ..

# Install server dependencies
echo "📦 Installing git-repo-snapshot server dependencies..."
cd servers/git-repo-snapshot
uv sync --all-extras
cd ../..

# Make scripts executable
echo "🔧 Making scripts executable..."
chmod +x scripts/*.sh

# Run initial formatting and linting
echo "🎨 Running initial formatting..."
./scripts/fmt.sh

echo "✅ Development environment setup complete!"
echo ""
echo "Next steps:"
echo "  1. Run tests: uv run pytest"
echo "  2. Start a server: ./scripts/run-stdio.sh git-repo-snapshot"
echo "  3. Format code: ./scripts/fmt.sh"