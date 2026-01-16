const std = @import("std");
const python = @cImport({
    @cInclude("Python.h");
});

/// Check if a number is prime using trial division
fn is_prime(n: i64) bool {
    if (n < 2) return false;
    if (n == 2) return true;
    if (n % 2 == 0) return false;

    var i: i64 = 3;
    const sqrt_n = @sqrt(@as(f64, @floatFromInt(n)));
    const limit: i64 = @intFromFloat(sqrt_n);

    while (i <= limit) : (i += 2) {
        if (n % i == 0) return false;
    }
    return true;
}

/// Count primes in a range [start, end]
fn count_primes_in_range(start: i64, end: i64) i64 {
    var count: i64 = 0;
    var i: i64 = start;
    while (i <= end) : (i += 1) {
        if (is_prime(i)) {
            count += 1;
        }
    }
    return count;
}

/// Export: Check if a number is prime (Python C-API)
/// Takes PyLong, returns PyBool
export fn zig_is_prime(self: ?*python.PyObject, args: ?*python.PyObject) callconv(.C) ?*python.PyObject {
    _ = self; // unused, but required for Python C-API

    var n: c_longlong = 0;

    // Parse arguments: expecting one integer
    if (python.PyArg_ParseTuple(args, "L", &n) == 0) {
        return null; // Python exception already set
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

/// Export: Count primes in range [start, end] (Python C-API)
/// Takes two PyLong integers, returns PyLong
export fn zig_count_primes(self: ?*python.PyObject, args: ?*python.PyObject) callconv(.C) ?*python.PyObject {
    _ = self; // unused

    var start: c_longlong = 0;
    var end: c_longlong = 0;

    // Parse arguments: expecting two integers
    if (python.PyArg_ParseTuple(args, "LL", &start, &end) == 0) {
        return null;
    }

    const count = count_primes_in_range(start, end);

    return python.PyLong_FromLongLong(count);
}

/// Export: Find the Nth prime number (Python C-API)
/// Takes PyLong n, returns PyLong (the nth prime)
export fn zig_nth_prime(self: ?*python.PyObject, args: ?*python.PyObject) callconv(.C) ?*python.PyObject {
    _ = self;

    var n: c_longlong = 0;

    if (python.PyArg_ParseTuple(args, "L", &n) == 0) {
        return null;
    }

    if (n <= 0) {
        python.PyErr_SetString(python.PyExc_ValueError, "n must be positive");
        return null;
    }

    var count: i64 = 0;
    var candidate: i64 = 2;

    while (count < n) {
        if (is_prime(candidate)) {
            count += 1;
            if (count == n) {
                return python.PyLong_FromLongLong(candidate);
            }
        }
        candidate += 1;
    }

    return python.PyLong_FromLongLong(candidate);
}

/// Method definitions for the module
const methods = [_]python.PyMethodDef{
    python.PyMethodDef{
        .ml_name = "is_prime",
        .ml_meth = zig_is_prime,
        .ml_flags = python.METH_VARARGS,
        .ml_doc = "Check if a number is prime. Usage: is_prime(n)",
    },
    python.PyMethodDef{
        .ml_name = "count_primes",
        .ml_meth = zig_count_primes,
        .ml_flags = python.METH_VARARGS,
        .ml_doc = "Count primes in range [start, end]. Usage: count_primes(start, end)",
    },
    python.PyMethodDef{
        .ml_name = "nth_prime",
        .ml_meth = zig_nth_prime,
        .ml_flags = python.METH_VARARGS,
        .ml_doc = "Find the Nth prime number. Usage: nth_prime(n)",
    },
    python.PyMethodDef{
        .ml_name = null,
        .ml_meth = null,
        .ml_flags = 0,
        .ml_doc = null,
    }, // Sentinel
};

/// Module definition
var module_def = python.PyModuleDef{
    .m_base = python.PyModuleDef_Base{
        .ob_base = python.PyObject{
            .ob_refcnt = 1,
            .ob_type = null,
        },
        .m_init = null,
        .m_index = 0,
        .m_copy = null,
    },
    .m_name = "zigprimes",
    .m_doc = "Fast prime number computation using Zig + Python C-API",
    .m_size = -1,
    .m_methods = @constCast(&methods),
    .m_slots = null,
    .m_traverse = null,
    .m_clear = null,
    .m_free = null,
};

/// Module initialization function (required for Python to load the module)
export fn PyInit_zigprimes() callconv(.C) ?*python.PyObject {
    return python.PyModule_Create(&module_def);
}
