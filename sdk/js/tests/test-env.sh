#!/bin/bash
# Shared Environment Setup for FlatAgents JavaScript Tests
# Provides common environment configuration and utility functions

set -e

# Colors for output
export RED='\033[0;31m'
export GREEN='\033[0;32m'
export YELLOW='\033[1;33m'
export BLUE='\033[0;34m'
export PURPLE='\033[0;35m'
export CYAN='\033[0;36m'
export NC='\033[0m' # No Color

# Detect OS
export OS=$(uname -s | tr '[:upper:]' '[:lower:]')
export IS_MACOS=false
export IS_LINUX=false
export IS_WINDOWS=false

case "$OS" in
  darwin*)
    export IS_MACOS=true
    ;;
  linux*)
    export IS_LINUX=true
    ;;
  mingw*|msys*|cygwin*)
    export IS_WINDOWS=true
    ;;
esac

# Common paths
export SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SDK_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export TESTS_ROOT="$SDK_ROOT/tests"
export BUILD_DIR="$SDK_ROOT/dist"
export SOURCE_DIR="$SDK_ROOT/src"

# Node.js version check
check_node_version() {
    if ! command -v node &> /dev/null; then
        echo -e "${RED}❌ Node.js is not installed. Please install Node.js (v18+) first.${NC}"
        exit 1
    fi
    
    local node_version=$(node --version | sed 's/v//')
    local required_version="18.0.0"
    
    if ! node -e "process.exit(process.version >= 'v18.0.0' ? 0 : 1)" 2>/dev/null; then
        echo -e "${RED}❌ Node.js v18+ is required. Found: $(node --version)${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✓ Node.js $(node --version) detected${NC}"
}

# npm version check
check_npm_version() {
    if ! command -v npm &> /dev/null; then
        echo -e "${RED}❌ npm is not installed. Please install npm first.${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✓ npm $(npm --version) detected${NC}"
}

# Install dependencies with error handling
install_dependencies() {
    local package_dir="${1:-$SDK_ROOT}"
    local install_args="${2:- --silent}"
    
    if [ ! -f "$package_dir/package.json" ]; then
        echo -e "${RED}❌ No package.json found in $package_dir${NC}"
        return 1
    fi
    
    echo -e "${YELLOW}📦 Installing dependencies in $(basename "$package_dir")...${NC}"
    cd "$package_dir"
    
    if ! npm install $install_args; then
        echo -e "${RED}❌ Failed to install dependencies${NC}"
        return 1
    fi
    
    echo -e "${GREEN}✓ Dependencies installed successfully${NC}"
}

# Build the project
build_project() {
    local build_root="${1:-$SDK_ROOT}"
    
    cd "$build_root"
    
    if [ ! -f "package.json" ]; then
        echo -e "${RED}❌ No package.json found in $build_root${NC}"
        return 1
    fi
    
    echo -e "${YELLOW}🏗️  Building project...${NC}"
    
    # Try different build scripts
    if npm run build 2>/dev/null; then
        echo -e "${GREEN}✓ Project built successfully${NC}"
    elif npm run build:ts 2>/dev/null; then
        echo -e "${GREEN}✓ Project built successfully (build:ts)${NC}"
    elif npm run compile 2>/dev/null; then
        echo -e "${GREEN}✓ Project compiled successfully${NC}"
    else
        echo -e "${YELLOW}⚠️  No build script found, continuing without build${NC}"
    fi
}

# Create test environment
setup_test_env() {
    echo -e "${CYAN}🔧 Setting up test environment...${NC}"
    
    # Create necessary directories
    mkdir -p "$TESTS_ROOT/test-data/fixtures"
    mkdir -p "$TESTS_ROOT/test-data/results"
    mkdir -p "$TESTS_ROOT/test-data/temp"
    mkdir -p "$BUILD_DIR"
    
    # Set permissions
    chmod +x "$TESTS_ROOT/run.sh"
    chmod +x "$TESTS_ROOT/integration/run.sh" 2>/dev/null || true
    chmod +x "$TESTS_ROOT/e2e/run.sh" 2>/dev/null || true
    
    # Environment variables for testing
    export FLATAGENTS_TEST_MODE=true
    export FLATAGENTS_ENV=test
    export NODE_ENV=test
    
    echo -e "${GREEN}✓ Test environment ready${NC}"
}

# Create package.json for tests if it doesn't exist
ensure_test_package() {
    local test_dir="$1"
    
    if [ ! -f "$test_dir/package.json" ]; then
        echo -e "${YELLOW}📄 Creating package.json for $(basename "$test_dir")${NC}"
        
        cat > "$test_dir/package.json" << 'EOF'
{
  "name": "flatagents-js-tests",
  "version": "1.0.0",
  "description": "Test suite for FlatAgents JavaScript SDK",
  "private": true,
  "type": "module",
  "scripts": {
    "test": "vitest",
    "test:unit": "vitest run",
    "test:integration": "vitest run integration",
    "test:e2e": "vitest run e2e",
    "test:watch": "vitest --watch",
    "test:coverage": "vitest run --coverage",
    "test:ui": "vitest --ui",
    "lint": "eslint . --ext .ts,.js",
    "lint:fix": "eslint . --ext .ts,.js --fix",
    "typecheck": "tsc --noEmit"
  },
  "devDependencies": {
    "vitest": "^2.0.0",
    "@vitest/coverage-v8": "^2.0.0",
    "@vitest/ui": "^2.0.0",
    "typescript": "^5.4.0",
    "@types/node": "^20.11.0",
    "eslint": "^8.57.0",
    "@typescript-eslint/eslint-plugin": "^7.0.0",
    "@typescript-eslint/parser": "^7.0.0",
    "jsdom": "^24.0.0"
  },
  "engines": {
    "node": ">=18.0.0",
    "npm": ">=9.0.0"
  }
}
EOF
    fi
}

# Create Vitest configuration if it doesn't exist
ensure_vitest_config() {
    local config_dir="$1"
    
    if [ ! -f "$config_dir/vitest.config.ts" ]; then
        echo -e "${YELLOW}⚙️  Creating Vitest configuration${NC}"
        
        cat > "$config_dir/vitest.config.ts" << 'EOF'
import { defineConfig } from 'vitest/config'
import { resolve } from 'path'

export default defineConfig({
  test: {
    globals: true,
    environment: 'node',
    include: ['**/*.test.ts', '**/*.spec.ts'],
    exclude: [
      'node_modules',
      'dist',
      '**/*.d.ts',
      'coverage'
    ],
    reporter: ['verbose', 'junit'],
    outputFile: {
      junit: './test-results/junit.xml'
    },
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html', 'lcov'],
      exclude: [
        'node_modules/',
        'dist/',
        '**/*.d.ts',
        '**/*.test.ts',
        '**/*.spec.ts',
        '**/fixtures/**',
        'vitest.config.ts'
      ],
      thresholds: {
        global: {
          branches: 70,
          functions: 70,
          lines: 70,
          statements: 70
        }
      }
    },
    hookTimeout: 30000,
    testTimeout: 15000,
    isolate: false,
    pool: 'threads',
    poolOptions: {
      threads: {
        maxThreads: 4,
        minThreads: 1
      }
    }
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, './src'),
      '@tests': resolve(__dirname, './tests')
    }
  },
  define: {
    'process.env.TEST': '"true"'
  }
})
EOF
    fi
}

# Cleanup function
cleanup_test_env() {
    local keep_env="${1:-false}"
    
    if [ "$keep_env" = false ]; then
        echo -e "${YELLOW}🧹 Cleaning up test environment...${NC}"
        rm -rf "$TESTS_ROOT/test-data/temp" 2>/dev/null || true
        rm -rf "$TESTS_ROOT/.nyc_output" 2>/dev/null || true
        rm -rf "$TESTS_ROOT/coverage" 2>/dev/null || true
    fi
}

# Print test summary
print_test_summary() {
    local passed=$1
    local failed=$2
    local total=$((passed + failed))
    
    echo ""
    echo "=============================================="
    if [ $failed -gt 0 ]; then
        echo -e "Test Summary: ${GREEN}$passed passed${NC}, ${RED}$failed failed${NC}"
    else
        echo -e "Test Summary: ${GREEN}$passed passed${NC}"
    fi
    echo -e "Total: $total tests"
    echo "=============================================="
    
    if [ $failed -gt 0 ]; then
        return 1
    else
        echo -e "${GREEN}🎉 All tests passed!${NC}"
        return 0
    fi
}

# Export all functions
export -f check_node_version
export -f check_npm_version
export -f install_dependencies
export -f build_project
export -f setup_test_env
export -f ensure_test_package
export -f ensure_vitest_config
export -f cleanup_test_env
export -f print_test_summary

echo -e "${GREEN}✓ FlatAgents test environment loaded${NC}"