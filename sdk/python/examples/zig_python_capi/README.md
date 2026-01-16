# Zig + Python C-API Demo with FlatAgents

> **Zig loves the Python C-API. It's C but without the brain damage.**

This demo showcases direct integration between Zig and Python using the Python C-API, with zero wrapper overhead. The computation is orchestrated by FlatMachine, with LLM agents generating tasks and analyzing results.

## What This Demonstrates

1. **Direct C-API Integration**: Zig's `@cImport` ingests `Python.h` for raw, zero-overhead Python extension development
2. **Performance**: Native-speed computations callable directly from Python
3. **FlatAgent Orchestration**: LLM agents generate computational tasks and analyze results
4. **Clean Architecture**: Zig handles compute, Python handles orchestration, LLMs handle intelligence

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     FlatMachine Orchestrator                │
└─────────────────────────────────────────────────────────────┘
                              │
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌──────────────┐    ┌──────────────────┐    ┌─────────────┐
│ Task         │    │ Zig Compute      │    │ Analyzer    │
│ Generator    │───▶│ (Python C-API)   │───▶│ Agent       │
│ Agent (LLM)  │    │                  │    │ (LLM)       │
└──────────────┘    └──────────────────┘    └─────────────┘
                            │
                            │
                    ┌───────┴────────┐
                    │  zigprimes.so  │
                    │  (Zig binary)  │
                    └────────────────┘
                            │
                    ┌───────┴────────┐
                    │ • is_prime()   │
                    │ • count_primes │
                    │ • nth_prime()  │
                    └────────────────┘
```

## How It Works

### 1. Zig Extension (`zig_src/prime_compute.zig`)

Zig uses `@cImport` to directly include `Python.h`:

```zig
const python = @cImport({
    @cInclude("Python.h");
});

export fn zig_is_prime(self: ?*python.PyObject, args: ?*python.PyObject)
    callconv(.C) ?*python.PyObject {
    var n: c_longlong = 0;

    if (python.PyArg_ParseTuple(args, "L", &n) == 0) {
        return null;
    }

    const result = is_prime(n);

    if (result) {
        _ = python.Py_INCREF(python.Py_True);
        return python.Py_True;
    } else {
        _ = python.Py_INCREF(python.Py_False);
        return python.Py_False;
    }
}
```

### 2. Compilation

Direct compilation to Python extension:

```bash
zig build-lib prime_compute.zig -dynamic -lc $(python3-config --includes)
```

The output is a native Python extension module (`zigprimes.so` / `zigprimes.pyd`).

### 3. Python Integration

No ctypes needed! Direct import as a native module:

```python
import zigprimes

# Direct C-API calls - zero overhead
is_prime = zigprimes.is_prime(17)           # True
count = zigprimes.count_primes(1, 100)      # 25
nth = zigprimes.nth_prime(10)                # 29
```

### 4. FlatMachine Orchestration

```yaml
states:
  generate_tasks:
    agent: task_generator  # LLM generates prime tasks

  execute_tasks:
    action: execute_zig_tasks  # Zig does the heavy lifting

  analyze_results:
    agent: analyzer  # LLM analyzes performance & patterns
```

## Quick Start

### Prerequisites

- **Zig**: [Install from ziglang.org](https://ziglang.org/download/)
- **Python 3.10+** with development headers
- **Python dev headers**:
  - Ubuntu/Debian: `sudo apt install python3-dev`
  - Fedora/RHEL: `sudo dnf install python3-devel`
  - macOS: Included with Python

### Run the Demo

```bash
./run.sh
```

That's it! The script will:
1. Build the Zig extension module
2. Install it to the Python package
3. Set up the Python environment
4. Run the demo

### Custom Options

```bash
# Generate 5 tasks per iteration
./run.sh --tasks 5

# Focus on specific computational areas
./run.sh --focus "small primes under 1000"

# Run more iterations
./run.sh --iterations 3

# Combine options
./run.sh --tasks 7 --focus "Mersenne primes" --iterations 2
```

## Manual Setup

If you prefer manual setup:

### 1. Build Zig Extension

```bash
cd zig_src
make
make install
cd ..
```

### 2. Set Up Python Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 3. Run

```bash
zig-capi-demo
```

## Example Output

```
======================================================================
🚀 ZIG + PYTHON C-API DEMO
======================================================================

Configuration:
  - Tasks per iteration: 3
  - Focus area: large primes and ranges
  - Max iterations: 2

======================================================================

▶️ State: generate_tasks

🎯 State: generate_tasks
[LLM generates creative prime computation tasks...]

⚡ State: execute_tasks

⚡ Executing 3 tasks with Zig...
----------------------------------------------------------------------

[Task 1/3] Check if 982,451,653 is prime
  Type: is_prime
  Params: {'n': 982451653}
  ✓ Result: 982451653 is PRIME
  Time: 0.000847s

[Task 2/3] Count primes between 1,000,000 and 1,100,000
  Type: count_primes
  Params: {'start': 1000000, 'end': 1100000}
  ✓ Result: 7216 primes in range [1000000, 1100000]
  Time: 0.125643s

[Task 3/3] Find the 50,000th prime number
  Type: nth_prime
  Params: {'n': 50000}
  ✓ Result: The 50000th prime is 611,953
  Time: 0.089234s

──────────────────────────────────────────────────────────────────────
Total Zig execution time: 0.215724s
──────────────────────────────────────────────────────────────────────

🔍 State: analyze_results
[LLM analyzes performance and mathematical patterns...]

✅ State: done

======================================================================
🎉 DEMO COMPLETE
======================================================================

Total iterations: 2

Final insights:
[Comprehensive analysis of prime computation performance and patterns]

======================================================================
```

## Key Features

### Zero Overhead

- No ctypes marshaling
- Direct Python C-API calls
- Native-speed execution
- Proper Python integration (GC-safe, exception handling)

### Type Safety

Zig provides compile-time safety while working with C APIs:

```zig
// Type-safe parsing with error handling
if (python.PyArg_ParseTuple(args, "L", &n) == 0) {
    return null;  // Python exception already set by PyArg_ParseTuple
}
```

### Production-Ready

The Zig module includes:
- Proper reference counting (`Py_INCREF`)
- Exception handling (`PyErr_SetString`)
- Module initialization (`PyInit_zigprimes`)
- Method documentation

## File Structure

```
zig_python_capi/
├── README.md                          # This file
├── run.sh                             # Quick start script
├── pyproject.toml                     # Python package config
├── config/                            # FlatAgent/Machine configs
│   ├── task_generator.yml            # LLM task generator
│   ├── analyzer.yml                  # LLM result analyzer
│   └── machine.yml                   # State machine orchestration
├── zig_src/                           # Zig source code
│   ├── prime_compute.zig             # Zig + Python C-API implementation
│   ├── build.zig                     # Zig build configuration
│   └── Makefile                      # Build automation
└── src/zig_python_capi/               # Python package
    ├── __init__.py
    └── main.py                       # Entry point + custom hooks
```

## Why Zig + Python C-API?

### Compared to ctypes:

❌ **ctypes**: Type marshaling overhead, manual struct packing, limited safety
✅ **Zig C-API**: Native speed, type safety, proper Python integration

### Compared to Cython:

❌ **Cython**: Python-like syntax that compiles to C, learning curve
✅ **Zig C-API**: Write real Zig, compile-time safety, better error messages

### Compared to PyO3 (Rust):

❌ **PyO3**: Complex build setup, larger binaries
✅ **Zig C-API**: Simple build, direct C-API control, smaller output

## Performance Notes

The demo tracks execution time for each Zig function call. On a typical system:

- `is_prime(n)` for 9-digit numbers: ~1ms
- `count_primes(1M, 1.1M)`: ~100-150ms
- `nth_prime(50000)`: ~80-100ms

These are **native speeds** with zero Python overhead.

## Learn More

- **Zig Documentation**: https://ziglang.org/documentation/master/
- **Python C-API**: https://docs.python.org/3/c-api/
- **FlatAgents**: See main repository README

## License

MIT (same as parent project)
