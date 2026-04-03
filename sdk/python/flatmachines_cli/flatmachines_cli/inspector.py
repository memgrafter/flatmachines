"""
Machine inspector — pretty-print machine structure.

Loads a flatmachine config and displays states, transitions, agents,
context, and structure as readable ASCII. No LLM needed.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml


def _dim(text: str) -> str:
    return f"\033[2m{text}\033[0m"


def _bold(text: str) -> str:
    return f"\033[1m{text}\033[0m"


def _cyan(text: str) -> str:
    return f"\033[36m{text}\033[0m"


def _green(text: str) -> str:
    return f"\033[32m{text}\033[0m"


def _yellow(text: str) -> str:
    return f"\033[33m{text}\033[0m"


def _red(text: str) -> str:
    return f"\033[31m{text}\033[0m"


def load_config(path: str) -> Dict[str, Any]:
    """Load and return raw machine config dict."""
    with open(path) as f:
        return yaml.safe_load(f)


def inspect_machine(path: str) -> str:
    """Return a formatted inspection of a machine config.

    Shows: name, states with transitions, agents, machines,
    context template, and structural notes.
    """
    config = load_config(path)
    data = config.get("data", {})
    metadata = config.get("metadata", {})
    states = data.get("states", {})
    agents = data.get("agents", {})
    machines = data.get("machines", {})
    context = data.get("context", {})
    persistence = data.get("persistence", {})

    lines: List[str] = []

    # Header
    name = data.get("name", "unnamed")
    lines.append(_bold(f"  {name}"))
    if metadata.get("description"):
        lines.append(f"  {_dim(metadata['description'])}")
    if metadata.get("tags"):
        lines.append(f"  {_dim('tags: ' + ', '.join(metadata['tags']))}")
    lines.append(f"  {_dim('spec: ' + config.get('spec_version', '?'))}")
    lines.append("")

    # State graph
    lines.append(_bold("  States"))
    initial_state = None
    final_states = set()
    for sname, sdata in states.items():
        if sdata.get("type") == "initial":
            initial_state = sname
        if sdata.get("type") == "final":
            final_states.add(sname)

    for sname, sdata in states.items():
        line = _format_state(sname, sdata, initial_state, final_states)
        lines.append(f"  {line}")
    lines.append("")

    # Agents
    if agents:
        lines.append(_bold("  Agents"))
        for aname, aref in agents.items():
            if isinstance(aref, str):
                lines.append(f"    {_cyan(aname)} → {_dim(aref)}")
            elif isinstance(aref, dict):
                atype = aref.get("type", "flatagent")
                lines.append(f"    {_cyan(aname)} [{atype}]")
            else:
                lines.append(f"    {_cyan(aname)}")
        lines.append("")

    # Peer machines
    if machines:
        lines.append(_bold("  Machines"))
        for mname, mref in machines.items():
            if isinstance(mref, str):
                lines.append(f"    {_cyan(mname)} → {_dim(mref)}")
            else:
                lines.append(f"    {_cyan(mname)}")
        lines.append("")

    # Context template
    if context:
        lines.append(_bold("  Context"))
        input_keys, static_keys = _classify_context(context)
        if input_keys:
            lines.append(f"    {_yellow('input required')}: {', '.join(input_keys)}")
        if static_keys:
            lines.append(f"    {_dim('static')}: {', '.join(static_keys)}")
        lines.append("")

    # Persistence
    if persistence and persistence.get("enabled"):
        backend = persistence.get("backend", "local")
        lines.append(f"  {_dim(f'persistence: {backend}')}")
        lines.append("")

    return "\n".join(lines)


def _format_state(
    name: str,
    sdata: Dict[str, Any],
    initial: Optional[str],
    finals: set,
) -> str:
    """Format a single state line with transitions."""
    parts = []

    # State name with type annotation
    if name == initial:
        parts.append(_green(f"● {name}"))
    elif name in finals:
        parts.append(_red(f"◼ {name}"))
    else:
        parts.append(f"  {name}")

    # What this state does
    annotations = []
    if sdata.get("agent"):
        annotations.append(f"agent:{sdata['agent']}")
    if sdata.get("machine"):
        m = sdata["machine"]
        if isinstance(m, list):
            annotations.append(f"parallel:[{','.join(m)}]")
        else:
            annotations.append(f"machine:{m}")
    if sdata.get("foreach"):
        annotations.append(f"foreach:{sdata['foreach']}")
    if sdata.get("launch"):
        annotations.append(f"launch:{sdata['launch']}")
    if sdata.get("action"):
        annotations.append(f"action:{sdata['action']}")
    if sdata.get("wait_for"):
        annotations.append(f"wait:{sdata['wait_for']}")
    if sdata.get("tool_loop"):
        tl = sdata["tool_loop"]
        annotations.append(f"tool_loop(max_turns={tl.get('max_turns', '?')})")

    if annotations:
        parts.append(_dim(f" [{', '.join(annotations)}]"))

    # Execution type
    execution = sdata.get("execution", {})
    if execution.get("type") and execution["type"] != "default":
        parts.append(_dim(f" ({execution['type']})"))

    # Transitions
    transitions = sdata.get("transitions", [])
    if transitions:
        targets = _format_transitions(transitions)
        parts.append(f" → {targets}")

    # Final state output
    if name in finals and sdata.get("output"):
        out_keys = list(sdata["output"].keys())
        parts.append(_dim(f" outputs: {', '.join(out_keys)}"))

    return "".join(parts)


def _format_transitions(transitions: List[Dict[str, Any]]) -> str:
    """Format transition targets, showing conditions."""
    if len(transitions) == 1 and not transitions[0].get("condition"):
        return transitions[0].get("to", "?")

    parts = []
    for t in transitions:
        target = t.get("to", "?")
        cond = t.get("condition")
        if cond:
            # Abbreviate long conditions
            if len(cond) > 40:
                cond = cond[:37] + "..."
            parts.append(f"{target} {_dim(f'if {cond}')}")
        else:
            parts.append(target)

    return " | ".join(parts)


def _classify_context(context: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """Split context keys into input-required and static/internal.

    Input-required: has {{ input.X }} template reference.
    Internal (None): initialized to null, filled by machine states.
    Static: has a default value with no input reference.
    """
    input_keys = []
    static_keys = []

    for key, val in context.items():
        if isinstance(val, str) and "input." in val:
            input_keys.append(key)
        else:
            # None values are internal state, not user input
            static_keys.append(key)

    return input_keys, static_keys


def show_context(path: str) -> str:
    """Show the context template and required input keys."""
    config = load_config(path)
    data = config.get("data", {})
    context = data.get("context", {})

    lines = []
    lines.append(_bold("  Context Template"))
    lines.append("")

    input_keys, static_keys = _classify_context(context)

    if input_keys:
        lines.append(f"  {_yellow('Input required')}:")
        for key in input_keys:
            val = context[key]
            if val is None:
                lines.append(f"    {_bold(key)}: {_dim('(prompted at runtime)')}")
            else:
                lines.append(f"    {_bold(key)}: {_dim(str(val))}")
        lines.append("")

    if static_keys:
        lines.append(f"  {_dim('Static/defaults')}:")
        for key in static_keys:
            val = context[key]
            display = str(val)
            if len(display) > 60:
                display = display[:57] + "..."
            lines.append(f"    {key}: {display}")
        lines.append("")

    return "\n".join(lines)


def validate_machine(path: str) -> str:
    """Run schema validation and return formatted results."""
    try:
        from flatmachines import validate_flatmachine_config
    except ImportError:
        return _red("  flatmachines not installed — cannot validate")

    config = load_config(path)
    lines = []

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            validate_flatmachine_config(config)
        except Exception as e:
            lines.append(_red(f"  Validation error: {e}"))
            return "\n".join(lines)

    if caught:
        lines.append(_yellow(f"  {len(caught)} warning(s):"))
        for w in caught:
            lines.append(f"    ⚠ {w.message}")
    else:
        lines.append(_green("  ✓ Valid"))

    return "\n".join(lines)
