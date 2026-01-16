const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    // Create shared library for Python extension
    const lib = b.addSharedLibrary(.{
        .name = "zigprimes",
        .root_source_file = b.path("prime_compute.zig"),
        .target = target,
        .optimize = optimize,
    });

    // Link against Python (system library)
    lib.linkLibC();
    lib.linkSystemLibrary("python3");

    // Add Python include path (will be detected from system)
    // Users may need to set this explicitly if Python is in a non-standard location

    // Install the library
    b.installArtifact(lib);
}
