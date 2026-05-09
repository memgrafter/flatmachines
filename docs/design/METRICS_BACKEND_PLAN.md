# Metrics Backend Design Plan

> **Status**: Planning
> **Version**: 0.1.0
> **Date**: 2026-01-25

## Overview

Design for local and LAN metrics backends that track execution metrics at two granularities:
1. **Per-Machine**: Individual machine/agent execution metrics
2. **Per-Run**: Aggregated metrics across an entire machine topology (workflow execution)

## Concepts

### Run
A **run** is a complete execution topology starting from a root machine and including all child machines spawned via `machine`, `foreach`, or `launch`. A run terminates when the root machine reaches a final state and all launched children complete.

```
Run (run_id: abc123)
├── RootMachine (execution_id: abc123)
│   ├── ChildMachine (execution_id: def456, parent: abc123)
│   │   └── GrandchildMachine (execution_id: ghi789, parent: def456)
│   └── LaunchedMachine (execution_id: jkl012, parent: abc123, launched: true)
```

### Run ID vs Execution ID
- `execution_id`: Unique per machine instance
- `run_id`: Shared by all machines in a topology (equals root `execution_id`)

## Existing Metrics (per-machine)

Already tracked in `MachineSnapshot`:
| Metric | Source | Description |
|--------|--------|-------------|
| `total_api_calls` | FlatAgent/FlatMachine | Cumulative LLM API calls |
| `total_cost` | FlatAgent/FlatMachine | Estimated cost ($0.001/1K input + $0.002/1K output) |
| `step` | FlatMachine | State transitions count |
| `created_at` | MachineSnapshot | Timestamps per checkpoint |

Already tracked in `MetricsHooks`:
| Metric | Source | Description |
|--------|--------|-------------|
| `state_counts` | MetricsHooks | Visits per state |
| `transition_counts` | MetricsHooks | Transitions per edge |
| `error_count` | MetricsHooks | Total errors |

## New Metrics Needed

### Per-Machine (extend existing)

| Metric | Type | Description |
|--------|------|-------------|
| `duration_ms` | int | Total execution time |
| `state_durations_ms` | Dict[str, int] | Time spent per state |
| `input_tokens` | int | Total input tokens |
| `output_tokens` | int | Total output tokens |
| `retries` | int | Retry attempts |
| `parallel_branches` | int | Max concurrent branches |

### Per-Run (new aggregation)

| Metric | Type | Description |
|--------|------|-------------|
| `run_id` | str | Root execution_id |
| `total_machines` | int | Machines in topology |
| `total_api_calls` | int | Sum across all machines |
| `total_cost` | float | Sum across all machines |
| `total_duration_ms` | int | Wall-clock time (root start → last child end) |
| `total_steps` | int | Sum of all state transitions |
| `topology_depth` | int | Max parent chain length |
| `machines_by_name` | Dict[str, int] | Count per machine type |
| `final_status` | str | success/error/timeout |
| `error_summary` | Dict[str, int] | Errors by type |

## Data Model

### MetricRecord (per-machine)

```python
@dataclass
class MachineMetrics:
    execution_id: str
    run_id: str  # NEW: root execution_id
    machine_name: str
    parent_execution_id: Optional[str]
    is_launched: bool  # fire-and-forget vs inline

    # Timing
    started_at: str  # ISO timestamp
    ended_at: Optional[str]
    duration_ms: Optional[int]

    # Existing metrics
    total_api_calls: int
    total_cost: float
    total_steps: int

    # New detailed metrics
    input_tokens: int
    output_tokens: int
    state_durations_ms: Dict[str, int]
    state_counts: Dict[str, int]
    transition_counts: Dict[str, int]
    error_count: int
    retries: int

    # Status
    final_state: Optional[str]
    final_status: str  # running/success/error/timeout
    last_error: Optional[str]
    last_error_type: Optional[str]
```

### RunMetrics (aggregated)

```python
@dataclass
class RunMetrics:
    run_id: str
    root_machine_name: str

    # Timing
    started_at: str
    ended_at: Optional[str]
    duration_ms: Optional[int]

    # Aggregates
    total_machines: int
    total_api_calls: int
    total_cost: float
    total_steps: int
    total_input_tokens: int
    total_output_tokens: int

    # Topology
    topology_depth: int
    machines_by_name: Dict[str, int]

    # Status
    final_status: str  # running/success/error/timeout
    machines_succeeded: int
    machines_failed: int
    error_summary: Dict[str, int]

    # Child tracking
    machine_ids: List[str]  # All execution_ids in run
```

## Backend Interface

```python
from abc import ABC, abstractmethod
from typing import Optional, List, AsyncIterator

class MetricsBackend(ABC):
    """Abstract metrics storage backend."""

    # Machine metrics
    @abstractmethod
    async def record_machine_start(self, metrics: MachineMetrics) -> None:
        """Record machine execution start."""
        pass

    @abstractmethod
    async def record_machine_end(self, execution_id: str, updates: dict) -> None:
        """Update machine metrics on completion."""
        pass

    @abstractmethod
    async def get_machine_metrics(self, execution_id: str) -> Optional[MachineMetrics]:
        """Get metrics for a specific machine."""
        pass

    # Run metrics
    @abstractmethod
    async def get_run_metrics(self, run_id: str) -> Optional[RunMetrics]:
        """Get aggregated metrics for entire run."""
        pass

    @abstractmethod
    async def list_runs(
        self,
        limit: int = 100,
        offset: int = 0,
        status: Optional[str] = None,
        machine_name: Optional[str] = None,
    ) -> List[RunMetrics]:
        """List runs with optional filters."""
        pass

    # Streaming (for live dashboards)
    @abstractmethod
    async def watch_run(self, run_id: str) -> AsyncIterator[MachineMetrics]:
        """Stream machine metrics updates for a run."""
        pass
```

## Local Backend

### Storage Format

```
.metrics/
├── runs/
│   ├── {run_id}/
│   │   ├── run.json           # RunMetrics (aggregated, updated incrementally)
│   │   ├── machines/
│   │   │   ├── {exec_id}.json # MachineMetrics
│   │   │   └── ...
│   │   └── events/            # Append-only event log
│   │       └── events.jsonl
├── index/
│   ├── by_status/
│   │   ├── running.txt        # Line-separated run_ids
│   │   ├── success.txt
│   │   └── error.txt
│   └── by_machine/
│       └── {machine_name}.txt # Line-separated run_ids
└── latest.txt                  # Last N run_ids for quick access
```

### Implementation

```python
class LocalMetricsBackend(MetricsBackend):
    """File-based metrics backend for single-node usage."""

    def __init__(self, base_dir: str = ".metrics"):
        self.base_dir = Path(base_dir)
        self._ensure_dirs()
        self._lock = asyncio.Lock()

    async def record_machine_start(self, metrics: MachineMetrics) -> None:
        run_dir = self.base_dir / "runs" / metrics.run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # Write machine metrics
        machine_path = run_dir / "machines" / f"{metrics.execution_id}.json"
        machine_path.parent.mkdir(exist_ok=True)
        await self._write_json(machine_path, asdict(metrics))

        # Update run metrics (create or increment)
        await self._update_run_metrics(metrics.run_id, metrics, is_start=True)

        # Append event
        await self._append_event(metrics.run_id, {
            "type": "machine_start",
            "execution_id": metrics.execution_id,
            "machine_name": metrics.machine_name,
            "timestamp": metrics.started_at,
        })

    async def record_machine_end(self, execution_id: str, updates: dict) -> None:
        # Find run_id from machine file
        run_id = await self._find_run_for_machine(execution_id)
        if not run_id:
            return

        machine_path = self.base_dir / "runs" / run_id / "machines" / f"{execution_id}.json"

        # Update machine metrics
        async with self._lock:
            data = await self._read_json(machine_path)
            data.update(updates)
            await self._write_json(machine_path, data)

        # Update run aggregates
        await self._update_run_metrics(run_id, MachineMetrics(**data), is_start=False)

    async def _update_run_metrics(
        self, run_id: str, machine: MachineMetrics, is_start: bool
    ) -> None:
        run_path = self.base_dir / "runs" / run_id / "run.json"

        async with self._lock:
            if run_path.exists():
                run_data = await self._read_json(run_path)
                run = RunMetrics(**run_data)
            else:
                # Initialize from first machine (root)
                run = RunMetrics(
                    run_id=run_id,
                    root_machine_name=machine.machine_name,
                    started_at=machine.started_at,
                    ended_at=None,
                    duration_ms=None,
                    total_machines=0,
                    total_api_calls=0,
                    total_cost=0.0,
                    total_steps=0,
                    total_input_tokens=0,
                    total_output_tokens=0,
                    topology_depth=1,
                    machines_by_name={},
                    final_status="running",
                    machines_succeeded=0,
                    machines_failed=0,
                    error_summary={},
                    machine_ids=[],
                )

            if is_start:
                run.total_machines += 1
                run.machine_ids.append(machine.execution_id)
                run.machines_by_name[machine.machine_name] = \
                    run.machines_by_name.get(machine.machine_name, 0) + 1
            else:
                # Update aggregates on completion
                run.total_api_calls += machine.total_api_calls
                run.total_cost += machine.total_cost
                run.total_steps += machine.total_steps
                run.total_input_tokens += machine.input_tokens
                run.total_output_tokens += machine.output_tokens

                if machine.final_status == "success":
                    run.machines_succeeded += 1
                elif machine.final_status == "error":
                    run.machines_failed += 1
                    if machine.last_error_type:
                        run.error_summary[machine.last_error_type] = \
                            run.error_summary.get(machine.last_error_type, 0) + 1

                # Check if run complete (root machine ended)
                if machine.execution_id == run_id:
                    run.ended_at = machine.ended_at
                    run.duration_ms = machine.duration_ms
                    run.final_status = machine.final_status

            await self._write_json(run_path, asdict(run))
```

## LAN Backend

### Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Machine A     │     │   Machine B     │     │   Machine C     │
│   (worker)      │     │   (worker)      │     │   (aggregator)  │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         └───────────────────────┴───────────────────────┘
                                 │
                    UDP Multicast / HTTP API
                                 │
                    ┌────────────┴────────────┐
                    │    Metrics Collector    │
                    │    (any node or dedicated)│
                    └─────────────────────────┘
```

### Discovery Protocol

Use UDP multicast for node discovery (similar to mDNS):

```python
MULTICAST_GROUP = "239.255.42.99"
MULTICAST_PORT = 4299

@dataclass
class NodeAnnouncement:
    node_id: str
    hostname: str
    http_port: int
    role: str  # "worker" | "aggregator" | "both"
    capabilities: List[str]
    timestamp: str
```

### HTTP API (per-node)

```
POST /metrics/machine          # Report machine metrics
POST /metrics/machine/{id}/end # Update on completion
GET  /metrics/run/{run_id}     # Get run metrics (aggregated)
GET  /metrics/runs             # List runs
WS   /metrics/watch/{run_id}   # WebSocket stream for live updates
```

### Implementation

```python
class LANMetricsBackend(MetricsBackend):
    """LAN-distributed metrics backend using HTTP + multicast discovery."""

    def __init__(
        self,
        node_id: Optional[str] = None,
        http_port: int = 4299,
        aggregator_url: Optional[str] = None,
        discovery_enabled: bool = True,
    ):
        self.node_id = node_id or str(uuid.uuid4())[:8]
        self.http_port = http_port
        self.aggregator_url = aggregator_url
        self.discovery_enabled = discovery_enabled

        # Local storage for this node's data
        self._local = LocalMetricsBackend(base_dir=f".metrics/{self.node_id}")

        # Known peers
        self._peers: Dict[str, NodeAnnouncement] = {}
        self._aggregator: Optional[str] = aggregator_url

    async def start(self) -> None:
        """Start discovery and HTTP server."""
        if self.discovery_enabled:
            asyncio.create_task(self._discovery_loop())
        asyncio.create_task(self._http_server())

    async def record_machine_start(self, metrics: MachineMetrics) -> None:
        # Store locally
        await self._local.record_machine_start(metrics)

        # Forward to aggregator if known
        if self._aggregator:
            await self._forward_to_aggregator("machine_start", metrics)

    async def get_run_metrics(self, run_id: str) -> Optional[RunMetrics]:
        # Try local first
        local = await self._local.get_run_metrics(run_id)
        if local:
            return local

        # Query aggregator or peers
        if self._aggregator:
            return await self._query_aggregator(f"/metrics/run/{run_id}")

        # Fan out to peers and merge
        return await self._query_peers_for_run(run_id)

    async def _discovery_loop(self) -> None:
        """Multicast discovery for peer nodes."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', MULTICAST_PORT))

        # Join multicast group
        mreq = struct.pack("4sl", socket.inet_aton(MULTICAST_GROUP), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        # Announce self periodically
        asyncio.create_task(self._announce_loop(sock))

        # Listen for peers
        while True:
            data, addr = await asyncio.get_event_loop().sock_recvfrom(sock, 1024)
            announcement = NodeAnnouncement(**json.loads(data))
            self._peers[announcement.node_id] = announcement

            # Auto-elect aggregator (lowest node_id)
            if not self._aggregator:
                aggregator = min(self._peers.values(), key=lambda n: n.node_id)
                self._aggregator = f"http://{aggregator.hostname}:{aggregator.http_port}"
```

### Aggregator Role

The aggregator node maintains the merged view:

```python
class MetricsAggregator:
    """Aggregates metrics from multiple LAN nodes."""

    def __init__(self, backend: LocalMetricsBackend):
        self.backend = backend
        self._pending_runs: Dict[str, RunMetrics] = {}

    async def receive_machine_metrics(self, metrics: MachineMetrics) -> None:
        """Called when a worker reports metrics."""
        # Store and aggregate
        await self.backend.record_machine_start(metrics)

        # Notify watchers
        await self._notify_watchers(metrics.run_id, metrics)

    async def get_aggregated_run(self, run_id: str) -> RunMetrics:
        """Get fully aggregated run metrics."""
        return await self.backend.get_run_metrics(run_id)
```

## Integration with Hooks

New `MetricsCollectorHooks` that reports to backend:

```python
class MetricsCollectorHooks(MachineHooks):
    """Hooks that report metrics to a MetricsBackend."""

    def __init__(
        self,
        backend: MetricsBackend,
        run_id: Optional[str] = None,  # Auto-detect from execution_id
    ):
        self.backend = backend
        self.run_id = run_id
        self._current_metrics: Optional[MachineMetrics] = None
        self._state_start_times: Dict[str, float] = {}

    async def on_machine_start(self, context: Dict[str, Any]) -> Dict[str, Any]:
        execution_id = context.get("_execution_id")
        parent_id = context.get("_parent_execution_id")

        # Determine run_id (root's execution_id)
        run_id = self.run_id or (parent_id if parent_id else execution_id)

        self._current_metrics = MachineMetrics(
            execution_id=execution_id,
            run_id=run_id,
            machine_name=context.get("_machine_name", "unknown"),
            parent_execution_id=parent_id,
            is_launched=context.get("_is_launched", False),
            started_at=datetime.now(timezone.utc).isoformat(),
            ended_at=None,
            duration_ms=None,
            total_api_calls=0,
            total_cost=0.0,
            total_steps=0,
            input_tokens=0,
            output_tokens=0,
            state_durations_ms={},
            state_counts={},
            transition_counts={},
            error_count=0,
            retries=0,
            final_state=None,
            final_status="running",
            last_error=None,
            last_error_type=None,
        )

        await self.backend.record_machine_start(self._current_metrics)
        return context

    async def on_state_enter(self, state_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        self._state_start_times[state_name] = time.time()
        self._current_metrics.state_counts[state_name] = \
            self._current_metrics.state_counts.get(state_name, 0) + 1
        self._current_metrics.total_steps += 1
        return context

    async def on_state_exit(
        self, state_name: str, context: Dict[str, Any], output: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        if state_name in self._state_start_times:
            duration = int((time.time() - self._state_start_times[state_name]) * 1000)
            self._current_metrics.state_durations_ms[state_name] = \
                self._current_metrics.state_durations_ms.get(state_name, 0) + duration
        return output

    async def on_machine_end(
        self, context: Dict[str, Any], final_output: Dict[str, Any]
    ) -> Dict[str, Any]:
        m = self._current_metrics
        m.ended_at = datetime.now(timezone.utc).isoformat()
        m.duration_ms = int(
            (datetime.fromisoformat(m.ended_at) - datetime.fromisoformat(m.started_at))
            .total_seconds() * 1000
        )
        m.final_status = "success"
        m.final_state = context.get("_current_state")

        # Pull aggregated metrics from machine
        m.total_api_calls = context.get("_total_api_calls", 0)
        m.total_cost = context.get("_total_cost", 0.0)

        await self.backend.record_machine_end(m.execution_id, asdict(m))
        return final_output

    async def on_error(
        self, state_name: str, error: Exception, context: Dict[str, Any]
    ) -> Optional[str]:
        self._current_metrics.error_count += 1
        self._current_metrics.last_error = str(error)
        self._current_metrics.last_error_type = type(error).__name__
        return None
```

## Configuration

### In machine spec

```yaml
spec: flatmachine
spec_version: "0.8.1"

metrics:
  backend: local  # local | lan | custom
  options:
    base_dir: .metrics
    # LAN options
    # aggregator_url: http://192.168.1.100:4299
    # discovery: true
```

### Environment variables

```bash
FLATAGENTS_METRICS_BACKEND=local        # local | lan
FLATAGENTS_METRICS_DIR=.metrics         # Local storage path
FLATAGENTS_METRICS_LAN_PORT=4299        # LAN HTTP port
FLATAGENTS_METRICS_AGGREGATOR=          # Explicit aggregator URL
```

## CLI Commands

```bash
# List recent runs
flatagents metrics list [--status=success|error|running] [--machine=name]

# Get run details
flatagents metrics run <run_id>

# Get machine details
flatagents metrics machine <execution_id>

# Watch live run
flatagents metrics watch <run_id>

# Export metrics
flatagents metrics export <run_id> --format=json|csv|prometheus
```

## Implementation Phases

### Phase 1: Core Data Model
- [ ] Define `MachineMetrics` and `RunMetrics` dataclasses
- [ ] Define `MetricsBackend` abstract interface
- [ ] Add `run_id` tracking to machine execution

### Phase 2: Local Backend
- [ ] Implement `LocalMetricsBackend`
- [ ] Implement `MetricsCollectorHooks`
- [ ] Add CLI commands for viewing metrics

### Phase 3: LAN Backend
- [ ] Implement UDP multicast discovery
- [ ] Implement HTTP API for metrics exchange
- [ ] Implement `LANMetricsBackend`
- [ ] Add WebSocket streaming for live updates

### Phase 4: Integration
- [ ] Add metrics configuration to machine spec
- [ ] Auto-enable metrics via environment variables
- [ ] Add Prometheus/OpenTelemetry export

## Open Questions

1. **Run completion detection**: How do we know when all launched machines are done? Options:
   - Poll until no machines in "running" state for run_id
   - Explicit "run complete" marker from root machine
   - Timeout-based completion

2. **Cross-machine run_id propagation**: How does a child machine know its run_id?
   - Pass in context: `_run_id`
   - Derive from parent_execution_id chain
   - Environment variable

3. **LAN security**: Should we add authentication for LAN discovery/API?
   - mTLS for production
   - Shared secret for simple setups
   - Trust local network (development only)

4. **Storage limits**: How do we handle metrics accumulation?
   - Time-based retention (delete after N days)
   - Count-based retention (keep last N runs)
   - Size-based rotation
