#!/bin/bash
set -e

echo "🎨 Formatting and linting Astra MCP codebase..."

# Format with ruff
echo "📝 Running ruff format..."
uv run ruff format .

# Fix imports and other auto-fixable issues
echo "🔧 Running ruff check --fix..."
uv run ruff check --fix .

# Sort imports
echo "📚 Sorting imports..."
uv run ruff check --select I --fix .

echo "✅ Formatting complete!"

# Optional: Run mypy type checking
if [ "$1" = "--check" ]; then
    echo "🔍 Running type checking..."
    uv run mypy .
    echo "✅ Type checking complete!"
fi