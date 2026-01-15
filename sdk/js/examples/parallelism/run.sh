#!/bin/bash

# FlatAgents Parallelism Demo Runner
# Handles setup and execution similar to Python examples

set -e

# Get the directory the script is located in (Python pattern)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Change to the script's directory first
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

LOCAL=false
DEV_MODE=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --local)
      LOCAL=true
      echo -e "${GREEN}Using local flatagents package${NC}"
      shift
      ;;
    --dev)
      DEV_MODE=true
      echo -e "${GREEN}Running in development mode${NC}"
      shift
      ;;
    -h|--help)
      echo "Usage: $0 [--local] [--dev]"
      echo ""
      echo "Options:"
      echo "  --local    Use local flatagents package (for development)"
      echo "  --dev      Run in development mode with tsx"
      echo "  --help     Show this help message"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

echo -e "${GREEN}🔧 Setting up FlatAgents Parallelism Demo${NC}"

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
    echo -e "${RED}❌ Node.js is not installed. Please install Node.js first.${NC}"
    exit 1
fi

# Check if npm is installed
if ! command -v npm &> /dev/null; then
    echo -e "${RED}❌ npm is not installed. Please install npm first.${NC}"
    exit 1
fi

# Install dependencies
echo -e "${YELLOW}📦 Installing dependencies...${NC}"
npm install

# Build the main package if --local is specified
if [ "$LOCAL" = true ]; then
    echo -e "${YELLOW}🏗️  Building local flatagents package...${NC}"
    cd ../../
    npm run build
    cd "$SCRIPT_DIR"
    npm install
fi

# Build TypeScript
echo -e "${YELLOW}🏗️  Building TypeScript...${NC}"
npm run build

# Run the demo
echo -e "${GREEN}🚀 Running Parallelism Demo...${NC}"
echo ""

if [ "$DEV_MODE" = true ]; then
    # Development mode with tsx
    npx tsx src/parallelism/main.ts
else
    # Production mode with built JavaScript
    node dist/parallelism/main.js
fi

echo ""
echo -e "${GREEN}✅ Demo completed!${NC}"