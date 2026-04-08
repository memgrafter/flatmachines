"""
Archive of all experiment generations for evolutionary search.

Unlike linear keep/discard, the archive preserves ALL generations —
including failures and regressions. This enables:
- Tree search with parent selection (not just hill-climbing)
- Stepping stones: worse variants can lead to breakthroughs
- Diversity: multiple lineages explore different regions

Storage: append-only JSONL file (archive.jsonl), one line per generation.
"""

from __future__ import annotations

import json
import math
import random
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ArchiveEntry:
    """One generation in the archive."""

    generation_id: int
    parent_id: Optional[int]  # Which generation this was derived from
    patch_file: str  # Path to the diff file
    score: Optional[float]  # Primary metric score (None if failed)
    scores: Dict[str, float] = field(default_factory=dict)  # All metrics
    status: str = "evaluated"  # "evaluated", "failed", "baseline"
    metadata: Dict[str, Any] = field(default_factory=dict)
    children: List[int] = field(default_factory=list)
    inner_iterations: int = 0  # How many inner loop iterations ran
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Archive:
    """Persistent archive of all experiment generations.

    Append-only JSONL storage. All generations are kept, not just winners.
    Supports multiple parent selection strategies for evolutionary search.
    """

    def __init__(self, path: str = "archive.jsonl"):
        self._path = Path(path)
        self._entries: Dict[int, ArchiveEntry] = {}
        self._next_id = 0
        self._load()

    @property
    def path(self) -> str:
        return str(self._path)

    @property
    def size(self) -> int:
        return len(self._entries)

    @property
    def entries(self) -> Dict[int, ArchiveEntry]:
        """Read-only access to all entries."""
        return dict(self._entries)

    def add(
        self,
        parent_id: Optional[int],
        patch_file: str,
        score: Optional[float] = None,
        scores: Optional[Dict[str, float]] = None,
        status: str = "evaluated",
        metadata: Optional[Dict[str, Any]] = None,
        inner_iterations: int = 0,
    ) -> ArchiveEntry:
        """Add a new generation to the archive. ALL generations are kept."""
        entry = ArchiveEntry(
            generation_id=self._next_id,
            parent_id=parent_id,
            patch_file=patch_file,
            score=score,
            scores=scores or {},
            status=status,
            metadata=metadata or {},
            inner_iterations=inner_iterations,
        )

        # Link parent → child
        if parent_id is not None and parent_id in self._entries:
            self._entries[parent_id].children.append(self._next_id)
            # Persist updated parent (re-write is fine, archive is small)
            self._persist_update(self._entries[parent_id])

        self._entries[self._next_id] = entry
        self._next_id += 1
        self._persist_append(entry)
        return entry

    def get(self, generation_id: int) -> Optional[ArchiveEntry]:
        """Get an entry by generation ID."""
        return self._entries.get(generation_id)

    def select_parent(self, method: str = "score_child_prop") -> Optional[ArchiveEntry]:
        """Select the next parent using the specified strategy.

        Methods:
        - "best": Always pick the highest-scoring generation
        - "score_child_prop": Score-proportional with child-count penalty (HyperAgents default)
        - "random": Uniform random among evaluated generations

        Returns None if archive is empty or has no evaluated entries.
        """
        candidates = {
            eid: e for eid, e in self._entries.items()
            if e.score is not None
        }
        if not candidates:
            return None

        if method == "best":
            return max(candidates.values(), key=lambda e: e.score)  # type: ignore

        if method == "random":
            return random.choice(list(candidates.values()))

        if method == "score_child_prop":
            return self._score_child_proportional(candidates)

        # Fallback to best
        return max(candidates.values(), key=lambda e: e.score)  # type: ignore

    def best_entry(self) -> Optional[ArchiveEntry]:
        """Return the highest-scoring entry."""
        scored = [e for e in self._entries.values() if e.score is not None]
        if not scored:
            return None
        return max(scored, key=lambda e: e.score)  # type: ignore

    def best_score(self) -> Optional[float]:
        """Return the best score in the archive."""
        best = self.best_entry()
        return best.score if best else None

    def get_lineage(self, generation_id: int) -> List[ArchiveEntry]:
        """Get the full ancestor chain from root to this generation."""
        chain: List[ArchiveEntry] = []
        current: Optional[int] = generation_id
        while current is not None:
            entry = self._entries.get(current)
            if entry is None:
                break
            chain.append(entry)
            current = entry.parent_id
        return list(reversed(chain))

    def get_patch_chain(self, generation_id: int) -> List[str]:
        """Get ordered list of patch files to reconstruct this generation."""
        return [e.patch_file for e in self.get_lineage(generation_id)]

    def summary_tsv(self) -> str:
        """Generate a TSV summary for the agent to read.

        Compact format optimized for LLM context efficiency.
        """
        lines = ["gen_id\tparent\tscore\tstatus\tchildren\tdescription"]
        for eid in sorted(self._entries.keys()):
            e = self._entries[eid]
            desc = e.metadata.get("description", "")[:60]
            score_str = f"{e.score:.4f}" if e.score is not None else "n/a"
            parent_str = str(e.parent_id) if e.parent_id is not None else "-"
            lines.append(
                f"{e.generation_id}\t{parent_str}\t{score_str}\t"
                f"{e.status}\t{len(e.children)}\t{desc}"
            )
        return "\n".join(lines)

    # --- Parent Selection Strategies ---

    def _score_child_proportional(
        self, candidates: Dict[int, ArchiveEntry]
    ) -> ArchiveEntry:
        """Sigmoid-scaled score × child-count penalty.

        From HyperAgents: balances exploitation (high scores) with
        exploration (under-explored branches).
        """
        entries = list(candidates.values())
        scores = [e.score for e in entries]  # type: ignore

        # Sigmoid around top-3 midpoint
        sorted_scores = sorted(scores, reverse=True)
        top_k = sorted_scores[: min(3, len(sorted_scores))]
        mid = sum(top_k) / len(top_k)

        # Scale factor: 10 works well for normalized scores, adjust for range
        score_range = max(scores) - min(scores) if len(scores) > 1 else 1.0  # type: ignore
        scale = 10.0 / max(score_range, 1e-6)

        scaled = []
        for s in scores:
            try:
                scaled.append(1.0 / (1.0 + math.exp(-scale * (s - mid))))  # type: ignore
            except OverflowError:
                scaled.append(0.0 if s < mid else 1.0)  # type: ignore

        # Child count penalty: penalize over-explored branches
        penalties = []
        for e in entries:
            n_children = len(e.children)
            penalties.append(math.exp(-((n_children / 8.0) ** 3)))

        # Combined weights
        weights = [s * p for s, p in zip(scaled, penalties)]

        # Ensure no zero weights (minimum exploration chance)
        total = sum(weights)
        if total == 0:
            return random.choice(entries)

        return random.choices(entries, weights=weights, k=1)[0]

    # --- Persistence ---

    def _persist_append(self, entry: ArchiveEntry) -> None:
        """Append a new entry to the JSONL file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a") as f:
            f.write(json.dumps(asdict(entry), default=str) + "\n")

    def _persist_update(self, entry: ArchiveEntry) -> None:
        """Rewrite the full file to update an existing entry.

        Only called when updating parent's children list.
        Archive files are small (hundreds of entries max).
        """
        if not self._path.exists():
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w") as f:
            for eid in sorted(self._entries.keys()):
                f.write(json.dumps(asdict(self._entries[eid]), default=str) + "\n")

    def _load(self) -> None:
        """Load archive from JSONL file."""
        if not self._path.exists():
            return

        max_id = -1
        for line in self._path.read_text().strip().split("\n"):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                entry = ArchiveEntry(**{
                    k: v for k, v in data.items()
                    if k in ArchiveEntry.__dataclass_fields__
                })
                self._entries[entry.generation_id] = entry
                max_id = max(max_id, entry.generation_id)
            except (json.JSONDecodeError, TypeError):
                continue

        self._next_id = max_id + 1 if max_id >= 0 else 0
