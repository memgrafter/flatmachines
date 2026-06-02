# JavaScript SDK Comprehensive Test Suite Plan

## Overview

This document outlines the comprehensive test suite plan for the FlatAgents JavaScript SDK, based on analysis of the Python SDK test patterns and current JavaScript SDK structure. The goal is to achieve complete coverage of all SDK functionality with both happy path and error path testing.

## Test Structure

```
sdk/js/tests/
├── unit/                          # Fast, isolated component tests
│   ├── flatagent.test.ts
│   ├── flatmachine.test.ts
│   ├── execution.test.ts          # [EXISTS - expand]
│   ├── persistence.test.ts        # [EXISTS - expand]
│   ├── expression.test.ts         # [EXISTS - expand]
│   ├── hooks.test.ts
│   ├── mcp.test.ts
│   ├── results.test.ts
│   └── utils.test.ts
├── integration/                   # Feature-complete workflows
│   ├── basic-workflows/
│   ├── parallelism/
│   ├── persistence/
│   ├── error-recovery/
│   └── mcp-integration/
├── e2e/                          # End-to-end with real services
│   └── examples/
├── fixtures/                     # Test data and utilities
│   ├── configs/                  # YAML configurations
│   ├── mocks/                    # Mock implementations
│   └── helpers.ts               # Test utilities
├── setup.ts                      # Global test setup
└── run-integration.sh            # Integration test runner
```

## Phase-Based Implementation

### Phase 1: Core Unit Tests (High Priority)

#### 1. FlatAgent Tests (`unit/flatagent.test.ts`)

**Configuration Loading:**
- Valid YAML config parsing
- Invalid config error handling
- Template rendering in prompts
- MCP tool configuration

**Execution:**
- Model selection (OpenAI/Anthropic)
- Prompt template rendering
- Structured output parsing
- Tool calling integration
- Error handling (rate limits, auth failures)

**Template Rendering:**
- Nunjucks template processing
- Context variable substitution
- Template error handling

#### 2. FlatMachine Tests (`unit/flatmachine.test.ts`)

**State Management:**
- State initialization
- State transitions
- Context propagation
- Final state handling

**Execution Patterns:**
- Sequential state execution
- Parallel machine execution
- Foreach dynamic parallelism
- Launch fire-and-forget

**Error Handling:**
- Transition error recovery
- On_error state routing
- Execution type error handling
- Context preservation on errors

#### 3. Supporting Module Tests

**Hooks Tests (`unit/hooks.test.ts`):**
- WebhookHooks HTTP calls
- CompositeHooks chaining
- Hook lifecycle event ordering
- Error handling in hooks

**MCP Tests (`unit/mcp.test.ts`):**
- Tool discovery and filtering
- Tool execution and results
- Multiple server management
- Error handling for missing tools

**Results Tests (`unit/results.test.ts`):**
- In-memory result storage
- Blocking reads with timeouts
- Concurrent result access
- Result cleanup

#### 4. Expand Existing Tests

**Execution Tests (`unit/execution.test.ts`):**
- [EXPAND] Add comprehensive retry scenarios
- [EXPAND] Backoff and jitter testing
- [EXPAND] Error type handling
- [EXPAND] Performance under load

**Persistence Tests (`unit/persistence.test.ts`):**
- [EXPAND] LocalFileBackend operations
- [EXPAND] Checkpoint serialization edge cases
- [EXPAND] Concurrent access patterns
- [EXPAND] File permission errors

**Expression Tests (`unit/expression.test.ts`):**
- [EXPAND] Complex expression combinations
- [EXPAND] Type coercion edge cases
- [EXPAND] Invalid expression error handling
- [EXPAND] Performance with large contexts

### Phase 2: Integration Tests (Medium Priority)

#### 1. Basic Workflows (`integration/basic-workflows/`)
- Simple state machines with transitions
- Conditional routing based on context
- Loop patterns with exit conditions
- Input/output mapping

#### 2. Parallelism (`integration/parallelism/`)
- Parallel machine arrays
- Settled vs any mode
- Foreach dynamic parallelism
- Launch fire-and-forget patterns
- Timeout handling

#### 3. Persistence (`integration/persistence/`)
- Local file backend persistence
- Memory backend for testing
- Resume after interrupted execution
- Multiple machine instances
- Checkpoint cleanup

#### 4. Error Recovery (`integration/error-recovery/`)
- Retry execution with backoffs
- On_error state transitions
- Graceful degradation
- Error context preservation

#### 5. MCP Integration (`integration/mcp-integration/`)
- Tool discovery and filtering
- Tool execution in agent calls
- Multiple MCP servers
- Tool error handling

### Phase 3: End-to-End Tests (Low Priority)

#### Example-Based Testing (`e2e/examples/`)
Using existing 14 YAML configuration examples:
- `helloworld/` - Simple loop with retry
- `parallelism/` - Parallel machines, foreach, launch
- `human-in-the-loop/` - Custom hooks
- `peering/` - Parent/child machines, results backend

## Test Data Strategy

### Fixtures Using Existing Examples

```typescript
// fixtures/configs/
├── helloworld/           # 4 YAML files
├── parallelism/          # 5 YAML files  
├── human-in-the-loop/    # 3 YAML files
└── peering/             # 2 YAML files

// fixtures/helpers.ts
export const loadTestConfig = (name: string) => {
  // Load YAML configuration for testing
}

export const createMockAgent = (overrides = {}) => {
  // Factory for test agents
}

export const createMockHooks = () => {
  // Mock hooks for testing
}
```

### Test Utilities

```typescript
// fixtures/helpers.ts
export const withCleanup = (testFn: () => Promise<void>) => {
  // Automatic resource cleanup
}

export const captureLogs = () => {
  // Log capture for verification
}

export const measurePerformance = (testFn: () => void) => {
  // Performance measurement utilities
}
```

## Error Path Testing

### Failure Injection Strategies

**Network Failures:**
```typescript
const mockNetworkFailure = () => {
  vi.mock('@ai-sdk/openai', () => ({
    openai: () => { throw new NetworkError() }
  }))
}
```

**Configuration Errors:**
- Missing required fields
- Invalid YAML syntax
- Conflicting options
- Type mismatches

**Resource Limits:**
- Out of memory scenarios
- Disk space exhaustion
- File permission errors
- Connection limits

### Error Scenarios Coverage

- **Network**: Connection failures, timeouts, rate limits
- **Authentication**: Invalid API keys, expired tokens
- **Configuration**: Invalid YAML, missing fields, type mismatches
- **Resources**: Out of memory, disk space, file permissions
- **Logic**: Infinite loops, unresolvable conditions
- **Integration**: External service failures, MCP server down

## Modern JavaScript Testing Practices

### 2026 Testing Standards

```typescript
// Vitest with native TypeScript
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Async/await throughout
describe('Async Operations', () => {
  it('handles async execution properly', async () => {
    const result = await agent.call(query)
    expect(result).toBeDefined()
  })
})

// Proper TypeScript typing
const createTestMachine = (config: MachineConfig): FlatMachine => {
  return new FlatMachine({ config })
}

// Mock ES modules
vi.mock('@ai-sdk/openai', () => ({
  openai: vi.fn()
}))
```

### Following Python SDK Patterns

- **Test Class Organization**: Descriptive class names and docstrings
- **Custom Hooks for Test Scenarios**: Test hooks that can simulate failures
- **Fixture-based Cleanup**: Automatic resource cleanup
- **Config Factory Pattern**: Minimal and comprehensive test configurations
- **Error Testing**: Comprehensive error injection and verification

## Implementation Guidelines

### Test Writing Standards

1. **Descriptive Names**: Test and class names should clearly describe what's being tested
2. **AAA Pattern**: Arrange, Act, Assert structure
3. **Isolation**: Each test should be independent and not rely on other tests
4. **Mocking**: Mock external dependencies to ensure deterministic tests
5. **Cleanup**: Automatic cleanup of resources and temporary files
6. **Error Verification**: Test both success and failure scenarios

### Coverage Requirements

- **Happy Path**: All documented features should work as expected
- **Error Path**: All error conditions should be handled gracefully
- **Edge Cases**: Boundary conditions and invalid inputs
- **Integration**: Cross-component functionality
- **Performance**: Resource usage and execution time

### Running Tests

```bash
# Run all unit tests
npm test

# Run integration tests
./tests/run-integration.sh

# Run with coverage
npm run test:coverage

# Run specific test file
npm test flatagent.test.ts
```

## Success Criteria

1. **Comprehensive Coverage**: All public APIs and major internal components tested
2. **Error Handling**: All error paths covered and verified
3. **Regression Prevention**: Example-based tests catch breaking changes
4. **Maintainability**: Clear test structure following established patterns
5. **Documentation**: Tests serve as usage examples and specifications

## Notes on Failing Tests

As per requirements:
- Any unit test that fails will be documented but NOT fixed
- Failures will be recorded in a separate FAILURES.md file
- Test implementation continues regardless of failures
- Focus is on comprehensive test coverage, not fixing existing issues

This plan provides a robust foundation for ensuring the JavaScript SDK meets the same quality standards as the Python SDK while following modern JavaScript testing practices.

## Implementation Checklist

### Phase 1: Core Unit Tests (High Priority)

#### Test Infrastructure Setup
- [ ] Create `tests/fixtures/` directory structure
- [ ] Create `tests/fixtures/helpers.ts` with test utilities
- [ ] Create `tests/fixtures/configs/` directories for YAML examples
- [ ] Copy existing YAML configs to test fixtures:
  - [ ] `helloworld/` (4 files)
  - [ ] `parallelism/` (5 files)
  - [ ] `human-in-the-loop/` (3 files)
  - [ ] `peering/` (2 files)
- [ ] Create `tests/fixtures/mocks/` for mock implementations
- [ ] Create `tests/setup.ts` for global test configuration
- [ ] Update `vitest.config.ts` to include new test paths

#### FlatAgent Unit Tests (`tests/unit/flatagent.test.ts`)
- [ ] Create test file structure with describe blocks
- [ ] **Configuration Loading Tests:**
  - [ ] Valid YAML config parsing
  - [ ] Invalid config error handling (missing fields, wrong types)
  - [ ] Template rendering in prompts
  - [ ] MCP tool configuration parsing
- [ ] **Execution Tests:**
  - [ ] Model selection (OpenAI vs Anthropic)
  - [ ] Prompt template rendering with context
  - [ ] Structured output parsing
  - [ ] Tool calling integration
  - [ ] Error handling (rate limits, auth failures, network errors)
- [ ] **Template Rendering Tests:**
  - [ ] Nunjucks template processing
  - [ ] Context variable substitution
  - [ ] Template error handling (missing variables, syntax errors)
- [ ] **Error Path Tests:**
  - [ ] Invalid API key handling
  - [ ] Rate limit error handling
  - [ ] Network timeout handling
  - [ ] Malformed response handling
  - [ ] Tool execution failures

#### FlatMachine Unit Tests (`tests/unit/flatmachine.test.ts`)
- [ ] Create test file structure with describe blocks
- [ ] **State Management Tests:**
  - [ ] State initialization with context
  - [ ] State transitions (conditional and unconditional)
  - [ ] Context propagation between states
  - [ ] Final state handling and output
- [ ] **Execution Pattern Tests:**
  - [ ] Sequential state execution
  - [ ] Parallel machine execution (machine: [a, b, c])
  - [ ] Foreach dynamic parallelism
  - [ ] Launch fire-and-forget patterns
- [ ] **Error Handling Tests:**
  - [ ] Transition error recovery
  - [ ] On_error state routing
  - [ ] Execution type error handling (retry failures)
  - [ ] Context preservation on errors
- [ ] **Configuration Tests:**
  - [ ] Machine configuration validation
  - [ ] Invalid state definitions
  - [ ] Circular transition detection
  - [ ] Missing initial/final state handling

#### Hooks Unit Tests (`tests/unit/hooks.test.ts`)
- [ ] Create test file structure
- [ ] **WebhookHooks Tests:**
  - [ ] HTTP webhook calls on lifecycle events
  - [ ] Webhook failure handling
  - [ ] Payload formatting and context
- [ ] **CompositeHooks Tests:**
  - [ ] Multiple hooks chaining
  - [ ] Hook failure propagation
  - [ ] Hook execution order
- [ ] **Lifecycle Tests:**
  - [ ] Hook event ordering (start/end, enter/exit, transition, error)
  - [ ] Context modification in hooks
  - [ ] Asynchronous hook handling
- [ ] **Error Path Tests:**
  - [ ] Hook execution failures
  - [ ] Malformed webhook responses
  - [ ] Hook timeout handling

#### MCP Unit Tests (`tests/unit/mcp.test.ts`)
- [ ] Create test file structure
- [ ] **Tool Discovery Tests:**
  - [ ] MCP server connection
  - [ ] Tool listing and filtering
  - [ ] Allow/deny pattern matching
- [ ] **Tool Execution Tests:**
  - [ ] Tool calling with parameters
  - [ ] Tool result parsing
  - [ ] Tool error handling
- [ ] **Multi-server Tests:**
  - [ ] Multiple MCP servers
  - [ ] Tool name conflicts
  - [ ] Server failure handling
- [ ] **Error Path Tests:**
  - [ ] MCP server unavailable
  - [ ] Invalid tool parameters
  - [ ] Tool execution timeouts

#### Results Unit Tests (`tests/unit/results.test.ts`)
- [ ] Create test file structure
- [ ] **Storage Tests:**
  - [ ] In-memory result storage
  - [ ] Result retrieval by key
  - [ ] Result expiration and cleanup
- [ ] **Blocking Tests:**
  - [ ] Blocking reads with timeouts
  - [ ] Concurrent read operations
  - [ ] Read timeout handling
- [ ] **Error Path Tests:**
  - [ ] Missing result keys
  - [ ] Timeout scenarios
  - [ ] Concurrent access conflicts

#### Expand Existing Tests

**Execution Tests (`tests/unit/execution.test.ts`):**
- [ ] **Existing Tests Review:**
  - [ ] Document current test coverage
  - [ ] Identify gaps in retry scenarios
- [ ] **Add Comprehensive Retry Tests:**
  - [ ] Multiple retry attempts with different backoffs
  - [ ] Jitter calculation and variation
  - [ ] Max retry limit enforcement
- [ ] **Error Type Handling:**
  - [ ] Different error types (RateLimitError, NetworkError, etc.)
  - [ ] Conditional retry logic
  - [ ] Non-retryable error handling
- [ ] **Performance Tests:**
  - [ ] Execution time measurement
  - [ ] Memory usage tracking
  - [ ] Concurrent execution handling

**Persistence Tests (`tests/unit/persistence.test.ts`):**
- [ ] **Existing Tests Review:**
  - [ ] Document current MemoryBackend coverage
  - [ ] Identify missing LocalFileBackend tests
- [ ] **Add LocalFileBackend Tests:**
  - [ ] File CRUD operations
  - [ ] Directory creation and permissions
  - [ ] Concurrent file access
- [ ] **Checkpoint Serialization Tests:**
  - [ ] Complex context serialization
  - [ ] Type preservation edge cases
  - [ ] Invalid data handling
- [ ] **Concurrent Access Tests:**
  - [ ] MultipleCheckpointManager instances
  - [ ] File locking scenarios
  - [ ] Race condition handling
- [ ] **Error Path Tests:**
  - [ ] File permission errors
  - [ ] Disk space exhaustion
  - [ ] Corrupted checkpoint files

**Expression Tests (`tests/unit/expression.test.ts`):**
- [ ] **Existing Tests Review:**
  - [ ] Document current expression coverage
  - [ ] Identify missing operator combinations
- [ ] **Complex Expression Tests:**
  - [ ] Nested boolean logic (and/or combinations)
  - [ ] Multiple operator precedence
  - [ ] Complex field access patterns
- [ ] **Type Coercion Tests:**
  - [ ] String to number comparisons
  - [ ] Null/undefined handling
  - [ ] Boolean conversion edge cases
- [ ] **Invalid Expression Tests:**
  - [ ] Syntax error handling
  - [ ] Unknown field references
  - [ ] Type mismatch errors
- [ ] **Performance Tests:**
  - [ ] Large context evaluation
  - [ ] Complex expression parsing
  - [ ] Memory usage optimization

### Phase 2: Integration Tests (Medium Priority)

#### Integration Infrastructure
- [ ] Create `tests/integration/` directory structure
- [ ] Create `tests/integration/basic-workflows/` directory
- [ ] Create `tests/integration/parallelism/` directory
- [ ] Create `tests/integration/persistence/` directory
- [ ] Create `tests/integration/error-recovery/` directory
- [ ] Create `tests/integration/mcp-integration/` directory
- [ ] Create `tests/run-integration.sh` script
- [ ] Add integration test configuration to vitest

#### Basic Workflows Integration Tests
- [ ] **Simple State Machine Tests:**
  - [ ] Linear state progression
  - [ ] Input/output mapping
  - [ ] Context initialization
- [ ] **Conditional Routing Tests:**
  - [ ] Condition-based transitions
  - [ ] Default transition handling
  - [ ] Multiple condition evaluation
- [ ] **Loop Pattern Tests:**
  - [ ] Self-referencing transitions
  - [ ] Loop exit conditions
  - [ ] Maximum step limits
- [ ] **Error Recovery Tests:**
  - [ ] State execution failures
  - [ ] Transition error handling
  - [ ] Graceful degradation

#### Parallelism Integration Tests
- [ ] **Parallel Machine Tests:**
  - [ ] `machine: [a, b, c]` execution
  - [ ] Settled mode (wait for all)
  - [ ] Any mode (wait for first)
  - [ ] Result aggregation
- [ ] **Foreach Dynamic Tests:**
  - [ ] Array iteration patterns
  - [ ] Key expression usage
  - [ ] Variable binding (as: parameter)
- [ ] **Launch Pattern Tests:**
  - [ ] Fire-and-forget execution
  - [ ] Input passing to launched machines
- [ ] **Timeout Tests:**
  - [ ] Parallel execution timeouts
  - [ ] Timeout handling and cleanup
- [ ] **Error Handling:**
  - [ ] Partial parallel failures
  - [ ] Error propagation in parallel

#### Persistence Integration Tests
- [ ] **File Backend Tests:**
  - [ ] Complete machine persistence
  - [ ] Resume after interruption
  - [ ] Multiple execution instances
- [ ] **Checkpoint Lifecycle Tests:**
  - [ ] Automatic checkpoint creation
  - [ ] Checkpoint cleanup
  - [ ] Orphaned checkpoint handling
- [ ] **Resume Scenarios:**
  - [ ] Resume after network failure
  - [ ] Resume after process crash
  - [ ] Resume with modified context
- [ ] **Concurrency Tests:**
  - [ ] Multiple machine persistence
  - [ ] Concurrent checkpoint access
- [ ] **Error Recovery:**
  - [ ] Corrupted checkpoint handling
  - [ ] Missing file recovery

#### Error Recovery Integration Tests
- [ ] **Retry Execution Tests:**
  - [ ] Backoff strategy verification
  - [ ] Jitter application
  - [ ] Maximum retry enforcement
- [ ] **Error State Transitions:**
  - [ ] On_error state routing
  - [ ] Error context preservation
  - [ ] Error type-specific handling
- [ ] **Graceful Degradation:**
  - [ ] Partial failure scenarios
  - [ ] Alternative execution paths
  - [ ] Fallback mechanisms
- [ ] **Resource Exhaustion:**
  - [ ] Memory limit handling
  - [ ] File space management
  - [ ] Connection limit recovery

#### MCP Integration Tests
- [ ] **Tool Discovery Tests:**
  - [ ] Real MCP server connections
  - [ ] Tool filtering and allow/deny
  - [ ] Server reconnection handling
- [ ] **Tool Execution Tests:**
  - [ ] End-to-end tool calling
  - [ ] Parameter passing and validation
  - [ ] Result parsing and mapping
- [ ] **Multi-server Tests:**
  - [ ] Multiple MCP server management
  - [ ] Tool name conflict resolution
  - [ ] Load balancing scenarios
- [ ] **Error Handling:**
  - [ ] Server unavailability
  - [ ] Tool execution failures
  - [ ] Network interruption recovery

### Phase 3: End-to-End Tests (Low Priority)

#### E2E Infrastructure
- [ ] Create `tests/e2e/` directory structure
- [ ] Create `tests/e2e/examples/` directory
- [ ] Set up real service integration (if available)
- [ ] Create E2E test configuration and environment

#### Example-Based E2E Tests
- [ ] **Hello World Examples:**
  - [ ] Execute all 4 helloworld YAML configs
  - [ ] Verify loop behavior and retry logic
  - [ ] Validate expected outputs
- [ ] **Parallelism Examples:**
  - [ ] Execute all 5 parallelism YAML configs
  - [ ] Verify parallel execution patterns
  - [ ] Validate foreach and launch behavior
- [ ] **Human-in-the-Loop Examples:**
  - [ ] Execute all 3 human-in-the-loop YAML configs
  - [ ] Verify custom hook integration
  - [ ] Validate webhook interactions
- [ ] **Peering Examples:**
  - [ ] Execute all 2 peering YAML configs
  - [ ] Verify parent/child machine relationships
  - [ ] Validate results backend usage
- [ ] **Regression Tests:**
  - [ ] All examples produce expected results
  - [ ] Performance benchmarks maintained
  - [ ] Error handling consistency

### Final Implementation Tasks

#### Documentation and Reporting
- [ ] Create `FAILURES.md` template for documenting test failures
- [ ] Update package.json with new test scripts:
  - [ ] `test:unit` - run only unit tests
  - [ ] `test:integration` - run only integration tests
  - [ ] `test:e2e` - run only e2e tests
  - [ ] `test:coverage` - run with coverage reporting
- [ ] Update README with test section
- [ ] Add test running instructions to documentation

#### Quality Assurance
- [ ] Run complete test suite
- [ ] Document all failing tests in FAILURES.md
- [ ] Generate coverage report
- [ ] Validate test isolation and independence
- [ ] Performance benchmarking
- [ ] Code review of all test files

#### Success Criteria Validation
- [ ] Verify comprehensive coverage of all public APIs
- [ ] Confirm all error paths are tested
- [ ] Validate example-based regression prevention
- [ ] Ensure maintainable test structure
- [ ] Confirm tests serve as documentation

---

## Implementation Notes

### Test Failure Policy
- **Document, Don't Fix**: Any failing tests will be recorded in `FAILURES.md`
- **Continue Implementation**: Test writing continues regardless of failures
- **Focus on Coverage**: Priority is comprehensive test coverage, not fixing existing bugs

### Progress Tracking
- Use this checklist to track implementation progress
- Mark items as complete when fully implemented
- Update checklist status in regular progress reviews

### Quality Standards
- Follow TypeScript best practices in all test files
- Use descriptive test names and clear documentation
- Ensure proper cleanup and resource management
- Mock external dependencies for deterministic results