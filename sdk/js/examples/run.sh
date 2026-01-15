#!/bin/bash

# FlatAgents Examples Runner
# Run all examples or a specific example

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

function show_help() {
    echo "FlatAgents Examples Runner"
    echo ""
    echo "Usage: $0 [example-name] [--dev] [--local]"
    echo ""
    echo "Examples:"
    echo "  helloworld          Simple Hello World demo"
    echo "  parallelism         Parallel execution demo"
    echo "  human-in-the-loop  Interactive human approval demo"
    echo "  peering             Distributed processing demo"
    echo ""
    echo "Options:"
    echo "  --dev     Run in development mode"
    echo "  --local   Use local flatagents package"
    echo "  --help    Show this help message"
    echo ""
    echo "Run without arguments to see this help."
}

function run_example() {
    local example=$1
    shift
    local args="$@"
    
    echo -e "${BLUE}🚀 Running ${example} example...${NC}"
    echo ""
    
    if [ ! -d "$example" ]; then
        echo -e "${RED}❌ Example '$example' not found.${NC}"
        echo "Available examples: helloworld, parallelism, human-in-the-loop, peering"
        exit 1
    fi
    
    cd "$example"
    
    if ! [ -f "run.sh" ]; then
        echo -e "${RED}❌ run.sh not found in $example directory.${NC}"
        exit 1
    fi
    
    # Make run.sh executable
    chmod +x run.sh
    
    # Run the example with any passed arguments
    ./run.sh $args
    
    cd ..
}

# Parse arguments
EXAMPLE=""
DEV=""
LOCAL=""

while [[ $# -gt 0 ]]; do
    case $1 in
        helloworld|parallelism|human-in-the-loop|peering)
            EXAMPLE="$1"
            shift
            ;;
        --dev)
            DEV="--dev"
            shift
            ;;
        --local)
            LOCAL="--local"
            shift
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            show_help
            exit 1
            ;;
    esac
done

if [ -z "$EXAMPLE" ]; then
    show_help
else
    run_example "$EXAMPLE" $DEV $LOCAL
fi