#!/usr/bin/env bash

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================"
echo "Zig + Python C-API Demo Setup"
echo "========================================"
echo

# Check for Zig
if ! command -v zig &> /dev/null; then
    echo "❌ Error: Zig compiler not found"
    echo "Please install Zig from: https://ziglang.org/download/"
    exit 1
fi

echo "✓ Zig found: $(zig version)"
echo

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python 3 not found"
    exit 1
fi

echo "✓ Python found: $(python3 --version)"
echo

# Step 1: Build Zig extension
echo "Step 1: Building Zig extension module..."
echo "----------------------------------------"
cd zig_src

if ! make clean; then
    echo "⚠️  Warning: make clean failed (might be first run)"
fi

if ! make; then
    echo "❌ Error: Failed to build Zig extension"
    echo "This might be due to missing Python development headers."
    echo "Try installing: python3-dev (Debian/Ubuntu) or python3-devel (Fedora/RHEL)"
    exit 1
fi

echo "✓ Built Zig extension"
echo

# Step 2: Install Zig extension to Python package
echo "Step 2: Installing Zig extension to package..."
if ! make install; then
    echo "❌ Error: Failed to install Zig extension"
    exit 1
fi

echo "✓ Installed Zig extension"
echo

cd "$SCRIPT_DIR"

# Step 3: Set up Python virtual environment
echo "Step 3: Setting up Python environment..."
echo "----------------------------------------"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    echo "✓ Created .venv"
else
    echo "✓ Virtual environment already exists"
fi

# Activate virtual environment
source .venv/bin/activate

echo "✓ Activated virtual environment"
echo

# Step 4: Install Python dependencies
echo "Step 4: Installing Python dependencies..."
echo "------------------------------------------"

# Upgrade pip
pip install --upgrade pip > /dev/null 2>&1

# Install the package in editable mode
pip install -e . > /dev/null 2>&1

echo "✓ Installed dependencies"
echo

# Step 5: Run the demo
echo "Step 5: Running demo..."
echo "========================================"
echo

# Run with default arguments or pass through user arguments
if [ $# -eq 0 ]; then
    zig-capi-demo
else
    zig-capi-demo "$@"
fi

echo
echo "========================================"
echo "Demo complete!"
echo "========================================"
echo
echo "To run again:"
echo "  ./run.sh                          # Default settings"
echo "  ./run.sh --tasks 5                # 5 tasks per iteration"
echo "  ./run.sh --focus 'small primes'   # Focus on small primes"
echo "  ./run.sh --iterations 3           # Run 3 iterations"
echo
