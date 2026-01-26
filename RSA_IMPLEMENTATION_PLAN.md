# RSA (Recursive Self-Aggregation) Implementation Plan for FlatAgents

> **Comprehensive implementation plan for adding RSA as an execution type in the FlatAgents framework**

## Table of Contents
1. [Algorithm Overview](#1-algorithm-overview)
2. [FlatAgents Integration Strategy](#2-flatagents-integration-strategy)
3. [Spec Changes](#3-spec-changes)
4. [Python SDK Implementation](#4-python-sdk-implementation)
5. [JavaScript SDK Implementation](#5-javascript-sdk-implementation)
6. [Configuration Examples](#6-configuration-examples)
7. [Testing Strategy](#7-testing-strategy)
8. [Implementation Phases](#8-implementation-phases)

---

## 1. Algorithm Overview

### 1.1 What is RSA?

Recursive Self-Aggregation (RSA) is a test-time scaling method that combines parallel and sequential reasoning approaches. Inspired by evolutionary algorithms, RSA maintains a population of candidate reasoning chains and iteratively refines them through aggregation.

**Key Research Sources:**
- [arXiv:2509.26626](https://arxiv.org/abs/2509.26626) - "Recursive Self-Aggregation Unlocks Deep Thinking in Large Language Models"
- [RSA Project Page](https://rsa-llm.github.io/)
- [GitHub Implementation](https://github.com/HyperPotatoNeo/RSA)

### 1.2 Core Parameters

| Parameter | Symbol | Description | Typical Value |
|-----------|--------|-------------|---------------|
| Population Size | N | Number of candidate solutions maintained | 16 |
| Aggregation Batch | K | Solutions subsampled per aggregation | 4 |
| Iterations | T | Number of refinement steps | 5-10 |

### 1.3 Algorithm Pseudocode

```
RSA(prompt, N, K, T):
    # Step 1: Generate initial population
    P_1 = [LLM.generate(prompt) for _ in range(N)]

    # Step 2: Iterative refinement
    for t in range(1, T+1):
        P_next = []
        for i in range(N):
            # Subsample K distinct solutions
            subset = random_sample(P_t, K)

            # Aggregate subset into improved solution
            improved = LLM.aggregate(prompt, subset)
            P_next.append(improved)

        P_t = P_next

    # Step 3: Final selection (majority vote or best)
    return select_best(P_T)
```

### 1.4 Key Characteristics

1. **Hybrid Scaling**: Combines parallel generation with sequential refinement
2. **Diversity Preservation**: Random subsampling maintains solution diversity
3. **No External Verification**: Uses LLM self-aggregation, no external oracle needed
4. **Full Chain Utilization**: Aggregates reasoning chains, not just final answers
5. **Evolutionary Inspiration**: Analogous to crossover in genetic algorithms

### 1.5 Aggregation Prompt Structure

The aggregation prompt presents K candidate solutions to the LLM and asks it to synthesize an improved solution:

```
You are given K candidate solutions to a problem. Analyze each solution:
- Identify correct reasoning steps
- Spot errors or inconsistencies
- Cross-reference conclusions

Synthesize the best elements into an improved, cohesive solution.

## Problem
{original_prompt}

## Candidate Solutions
{for each solution in subset}
### Solution {i}
{solution.reasoning_chain}
{solution.final_answer}
{end for}

## Your Task
Produce an improved solution by combining the strongest reasoning from the candidates.
Provide your complete reasoning chain and final answer.
```

---

## 2. FlatAgents Integration Strategy

### 2.1 Integration Point: Execution Type

RSA integrates naturally as a new **execution type** alongside existing types:

| Execution Type | Purpose |
|---------------|---------|
| `default` | Single agent call |
| `retry` | Retry with backoff on failure |
| `parallel` | N parallel calls, return all |
| `mdap_voting` | Multi-sample with consensus voting |
| **`rsa`** | **Recursive Self-Aggregation** |

### 2.2 Architecture Fit

```
┌─────────────────────────────────────────────────────────────┐
│                      FlatMachine                            │
│  ┌────────────────┐                                         │
│  │  State         │                                         │
│  │  ├─ agent: X   │                                         │
│  │  └─ execution: │                                         │
│  │      type: rsa │───────────────────────────────────────┐ │
│  │      n: 16     │                                       │ │
│  │      k: 4      │                                       │ │
│  │      t: 10     │                                       │ │
│  └────────────────┘                                       │ │
│                                                           │ │
│  ┌─────────────────────────────────────────────────────┐  │ │
│  │               RSAExecution                          │←─┘ │
│  │  ┌───────────────────────────────────────────────┐  │    │
│  │  │  Step 1: Generate N initial solutions         │  │    │
│  │  │          (parallel agent.call())              │  │    │
│  │  └───────────────────────────────────────────────┘  │    │
│  │  ┌───────────────────────────────────────────────┐  │    │
│  │  │  Step 2: T iterations of:                     │  │    │
│  │  │    - Subsample K solutions                    │  │    │
│  │  │    - Aggregate via aggregator agent           │  │    │
│  │  └───────────────────────────────────────────────┘  │    │
│  │  ┌───────────────────────────────────────────────┐  │    │
│  │  │  Step 3: Select best from final population    │  │    │
│  │  └───────────────────────────────────────────────┘  │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 Design Decisions

#### 2.3.1 Aggregator Agent Options

**Option A: Inline Aggregator (Recommended)**
- RSA execution type includes a built-in aggregation prompt template
- Simpler configuration, fewer files
- Aggregator inherits model config from parent agent

**Option B: Separate Aggregator Agent**
- User specifies a separate agent for aggregation
- More flexible but requires additional configuration
- Useful for custom aggregation strategies

**Recommendation**: Support both, with inline as default.

#### 2.3.2 Selection Strategy Options

| Strategy | Description |
|----------|-------------|
| `majority_vote` | Most common final answer wins |
| `last_iteration` | Return first solution from final population |
| `best_reasoning` | Use LLM to pick best from final population |
| `all` | Return entire final population |

#### 2.3.3 Parallelism Strategy

- **Initial generation**: Fully parallel (N concurrent calls)
- **Each iteration**: Parallel aggregations (N concurrent calls)
- **Total API calls**: `N + (T * N)` = `N * (1 + T)`

For N=16, T=10: 176 total API calls

---

## 3. Spec Changes

### 3.1 flatmachine.d.ts Changes

```typescript
// Add RSA to ExecutionConfig type union (line 344)
export interface ExecutionConfig {
  type: "default" | "retry" | "parallel" | "mdap_voting" | "rsa";

  // Existing fields
  backoffs?: number[];
  jitter?: number;
  n_samples?: number;
  k_margin?: number;
  max_candidates?: number;

  // NEW: RSA-specific fields
  population_size?: number;      // N: population size (default: 16)
  aggregation_k?: number;        // K: solutions per aggregation (default: 4)
  iterations?: number;           // T: number of refinement steps (default: 5)
  selection?: "majority_vote" | "last_iteration" | "best_reasoning" | "all";
  aggregator?: string;           // Optional: path to aggregator agent
  aggregation_prompt?: string;   // Optional: custom aggregation prompt template
  extract_answer?: string;       // Optional: regex to extract final answer for voting
}
```

### 3.2 flatagents-runtime.d.ts Changes

```typescript
// Add RSA metrics interface
export interface RSAMetrics {
  population_size: number;
  aggregation_k: number;
  iterations_completed: number;
  total_api_calls: number;
  final_population_diversity: number;  // Unique answers / population size
  selection_confidence: number;        // For majority_vote: winner count / population
}

// Extend ExecutionType interface
export interface RSAExecutionType extends ExecutionType {
  getMetrics(): RSAMetrics;
}
```

---

## 4. Python SDK Implementation

### 4.1 New File: `sdk/python/flatagents/rsa.py`

```python
"""
RSA (Recursive Self-Aggregation) Execution Type.

Implements the RSA algorithm from arXiv:2509.26626.
"""

import asyncio
import random
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .execution import ExecutionType, register_execution_type
from .monitoring import get_logger

if TYPE_CHECKING:
    from .flatagent import FlatAgent

logger = get_logger(__name__)


@dataclass
class RSAMetrics:
    """Metrics collected during RSA execution."""
    population_size: int = 0
    aggregation_k: int = 0
    iterations_completed: int = 0
    total_api_calls: int = 0
    generation_calls: int = 0
    aggregation_calls: int = 0
    final_population_diversity: float = 0.0
    selection_confidence: float = 0.0
    iterations_detail: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class Solution:
    """A candidate solution with reasoning chain and answer."""
    reasoning_chain: str
    final_answer: Optional[str] = None
    raw_output: Optional[Dict[str, Any]] = None

    def __hash__(self):
        return hash(self.final_answer or self.reasoning_chain[:100])


DEFAULT_AGGREGATION_PROMPT = """You are given {k} candidate solutions to a problem. Your task is to analyze each solution, identify the strongest reasoning, and synthesize an improved solution.

## Analysis Guidelines
1. Examine each solution's reasoning chain carefully
2. Identify correct reasoning steps and valid conclusions
3. Spot errors, inconsistencies, or logical flaws
4. Cross-reference conclusions across solutions
5. Note which solutions have the most rigorous reasoning

## Original Problem
{original_prompt}

## Candidate Solutions
{solutions_text}

## Your Task
Synthesize the best elements from the candidate solutions into a single, improved solution:
1. Combine the strongest reasoning steps
2. Correct any errors you identified
3. Ensure logical consistency throughout
4. Provide your complete reasoning chain
5. State your final answer clearly

Provide your improved solution:"""


@register_execution_type("rsa")
class RSAExecution(ExecutionType):
    """
    Recursive Self-Aggregation execution type.

    Implements evolutionary-inspired test-time scaling by maintaining
    a population of solutions and iteratively refining through aggregation.

    Example YAML:
        execution:
          type: rsa
          population_size: 16    # N: number of candidate solutions
          aggregation_k: 4       # K: solutions per aggregation batch
          iterations: 5          # T: refinement iterations
          selection: majority_vote
    """

    def __init__(
        self,
        population_size: int = 16,
        aggregation_k: int = 4,
        iterations: int = 5,
        selection: str = "majority_vote",
        aggregator: Optional[str] = None,
        aggregation_prompt: Optional[str] = None,
        extract_answer: Optional[str] = None,
    ):
        self.population_size = population_size
        self.aggregation_k = aggregation_k
        self.iterations = iterations
        self.selection = selection
        self.aggregator = aggregator
        self.aggregation_prompt = aggregation_prompt or DEFAULT_AGGREGATION_PROMPT
        self.extract_answer = extract_answer
        self.metrics = RSAMetrics()

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "RSAExecution":
        return cls(
            population_size=config.get("population_size", 16),
            aggregation_k=config.get("aggregation_k", 4),
            iterations=config.get("iterations", 5),
            selection=config.get("selection", "majority_vote"),
            aggregator=config.get("aggregator"),
            aggregation_prompt=config.get("aggregation_prompt"),
            extract_answer=config.get("extract_answer"),
        )

    def _extract_answer(self, content: str) -> Optional[str]:
        """Extract final answer from response for voting."""
        if not self.extract_answer:
            # Default: use last non-empty line or full content
            lines = [l.strip() for l in content.strip().split('\n') if l.strip()]
            return lines[-1] if lines else content

        import re
        match = re.search(self.extract_answer, content, re.DOTALL)
        return match.group(1) if match else None

    def _format_solutions_for_aggregation(self, solutions: List[Solution]) -> str:
        """Format solutions for the aggregation prompt."""
        parts = []
        for i, sol in enumerate(solutions, 1):
            parts.append(f"### Solution {i}")
            parts.append(sol.reasoning_chain)
            if sol.final_answer:
                parts.append(f"\n**Final Answer**: {sol.final_answer}")
            parts.append("")
        return "\n".join(parts)

    async def _generate_initial_population(
        self,
        agent: "FlatAgent",
        input_data: Dict[str, Any]
    ) -> List[Solution]:
        """Generate N initial solutions in parallel."""
        async def single_call() -> Optional[Solution]:
            try:
                result = await agent.call(**input_data)
                content = ""
                if result.output:
                    content = str(result.output.get("content", result.output))
                elif result.content:
                    content = result.content

                return Solution(
                    reasoning_chain=content,
                    final_answer=self._extract_answer(content),
                    raw_output=result.output
                )
            except Exception as e:
                logger.warning(f"Generation failed: {e}")
                return None

        tasks = [single_call() for _ in range(self.population_size)]
        results = await asyncio.gather(*tasks)

        valid = [r for r in results if r is not None]
        self.metrics.generation_calls += len(tasks)
        self.metrics.total_api_calls += len(tasks)

        logger.info(f"Generated {len(valid)}/{self.population_size} initial solutions")
        return valid

    async def _aggregate_subset(
        self,
        agent: "FlatAgent",
        original_prompt: str,
        subset: List[Solution]
    ) -> Optional[Solution]:
        """Aggregate K solutions into an improved solution."""
        solutions_text = self._format_solutions_for_aggregation(subset)

        aggregation_input = self.aggregation_prompt.format(
            k=len(subset),
            original_prompt=original_prompt,
            solutions_text=solutions_text
        )

        try:
            # Use the same agent with modified input for aggregation
            result = await agent.call(aggregation_task=aggregation_input)
            content = ""
            if result.output:
                content = str(result.output.get("content", result.output))
            elif result.content:
                content = result.content

            self.metrics.aggregation_calls += 1
            self.metrics.total_api_calls += 1

            return Solution(
                reasoning_chain=content,
                final_answer=self._extract_answer(content),
                raw_output=result.output
            )
        except Exception as e:
            logger.warning(f"Aggregation failed: {e}")
            # On failure, return random solution from subset
            return random.choice(subset)

    async def _run_iteration(
        self,
        agent: "FlatAgent",
        original_prompt: str,
        population: List[Solution],
        iteration: int
    ) -> List[Solution]:
        """Run one iteration of RSA refinement."""
        new_population = []

        async def aggregate_one() -> Solution:
            # Sample K distinct solutions
            subset = random.sample(
                population,
                min(self.aggregation_k, len(population))
            )
            result = await self._aggregate_subset(agent, original_prompt, subset)
            return result if result else random.choice(subset)

        # Run N aggregations in parallel
        tasks = [aggregate_one() for _ in range(self.population_size)]
        results = await asyncio.gather(*tasks)
        new_population = [r for r in results if r is not None]

        # Record iteration metrics
        unique_answers = len(set(s.final_answer for s in new_population if s.final_answer))
        self.metrics.iterations_detail.append({
            "iteration": iteration,
            "population_size": len(new_population),
            "unique_answers": unique_answers,
            "diversity": unique_answers / max(len(new_population), 1)
        })

        logger.info(f"Iteration {iteration}: {len(new_population)} solutions, {unique_answers} unique")
        return new_population

    def _select_final(self, population: List[Solution]) -> Optional[Dict[str, Any]]:
        """Select final answer from population."""
        if not population:
            return None

        if self.selection == "all":
            return {
                "solutions": [s.raw_output or {"content": s.reasoning_chain} for s in population],
                "count": len(population)
            }

        if self.selection == "last_iteration":
            winner = population[0]
            return winner.raw_output or {"content": winner.reasoning_chain}

        # majority_vote or best_reasoning - use voting
        votes = Counter(s.final_answer for s in population if s.final_answer)

        if not votes:
            # No extractable answers, return first
            winner = population[0]
            return winner.raw_output or {"content": winner.reasoning_chain}

        winner_answer, winner_count = votes.most_common(1)[0]
        self.metrics.selection_confidence = winner_count / len(population)

        # Find a solution with the winning answer
        for sol in population:
            if sol.final_answer == winner_answer:
                return sol.raw_output or {"content": sol.reasoning_chain}

        return population[0].raw_output or {"content": population[0].reasoning_chain}

    async def execute(
        self,
        agent: "FlatAgent",
        input_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Execute RSA algorithm.

        1. Generate N initial solutions
        2. For T iterations: aggregate K-subsets to produce new population
        3. Select final answer via voting or other strategy
        """
        # Reset metrics
        self.metrics = RSAMetrics(
            population_size=self.population_size,
            aggregation_k=self.aggregation_k
        )

        # Extract original prompt for aggregation context
        original_prompt = str(input_data)

        # Step 1: Generate initial population
        logger.info(f"RSA: Generating {self.population_size} initial solutions")
        population = await self._generate_initial_population(agent, input_data)

        if not population:
            logger.error("RSA: Failed to generate any initial solutions")
            return None

        # Step 2: Iterative refinement
        for t in range(1, self.iterations + 1):
            logger.info(f"RSA: Starting iteration {t}/{self.iterations}")
            population = await self._run_iteration(agent, original_prompt, population, t)
            self.metrics.iterations_completed = t

            if not population:
                logger.error(f"RSA: Population empty after iteration {t}")
                return None

        # Calculate final diversity
        unique_answers = len(set(s.final_answer for s in population if s.final_answer))
        self.metrics.final_population_diversity = unique_answers / max(len(population), 1)

        # Step 3: Select final answer
        logger.info(f"RSA: Selecting final answer using {self.selection} strategy")
        result = self._select_final(population)

        # Add metrics to result if dict
        if isinstance(result, dict):
            result["_rsa_metrics"] = self.get_metrics()

        return result

    def get_metrics(self) -> Dict[str, Any]:
        """Get collected metrics."""
        return {
            "population_size": self.metrics.population_size,
            "aggregation_k": self.metrics.aggregation_k,
            "iterations_completed": self.metrics.iterations_completed,
            "total_api_calls": self.metrics.total_api_calls,
            "generation_calls": self.metrics.generation_calls,
            "aggregation_calls": self.metrics.aggregation_calls,
            "final_population_diversity": self.metrics.final_population_diversity,
            "selection_confidence": self.metrics.selection_confidence,
            "iterations_detail": self.metrics.iterations_detail,
        }


__all__ = ["RSAExecution", "RSAMetrics", "Solution"]
```

### 4.2 Update `execution.py`

Add import at the end of `sdk/python/flatagents/execution.py`:

```python
# Import RSA execution type (registers via decorator)
from .rsa import RSAExecution
```

### 4.3 Update `__init__.py`

Add to exports in `sdk/python/flatagents/__init__.py`:

```python
from .rsa import RSAExecution, RSAMetrics

__all__ = [
    # ... existing exports ...
    "RSAExecution",
    "RSAMetrics",
]
```

---

## 5. JavaScript SDK Implementation

### 5.1 Update `sdk/js/src/execution.ts`

```typescript
import { ExecutionConfig, ExecutionType } from './types';

// ... existing classes ...

export interface RSASolution {
  reasoningChain: string;
  finalAnswer?: string;
  rawOutput?: Record<string, any>;
}

export interface RSAMetrics {
  populationSize: number;
  aggregationK: number;
  iterationsCompleted: number;
  totalApiCalls: number;
  generationCalls: number;
  aggregationCalls: number;
  finalPopulationDiversity: number;
  selectionConfidence: number;
}

const DEFAULT_AGGREGATION_PROMPT = `You are given {k} candidate solutions to a problem. Your task is to analyze each solution, identify the strongest reasoning, and synthesize an improved solution.

## Analysis Guidelines
1. Examine each solution's reasoning chain carefully
2. Identify correct reasoning steps and valid conclusions
3. Spot errors, inconsistencies, or logical flaws
4. Cross-reference conclusions across solutions
5. Note which solutions have the most rigorous reasoning

## Original Problem
{original_prompt}

## Candidate Solutions
{solutions_text}

## Your Task
Synthesize the best elements from the candidate solutions into a single, improved solution.

Provide your improved solution:`;

export class RSAExecution implements ExecutionType {
  private metrics: RSAMetrics;

  constructor(
    private populationSize = 16,
    private aggregationK = 4,
    private iterations = 5,
    private selection: 'majority_vote' | 'last_iteration' | 'best_reasoning' | 'all' = 'majority_vote',
    private aggregationPrompt = DEFAULT_AGGREGATION_PROMPT,
    private extractAnswerPattern?: string,
  ) {
    this.metrics = this.initMetrics();
  }

  private initMetrics(): RSAMetrics {
    return {
      populationSize: this.populationSize,
      aggregationK: this.aggregationK,
      iterationsCompleted: 0,
      totalApiCalls: 0,
      generationCalls: 0,
      aggregationCalls: 0,
      finalPopulationDiversity: 0,
      selectionConfidence: 0,
    };
  }

  private extractAnswer(content: string): string | undefined {
    if (!this.extractAnswerPattern) {
      const lines = content.trim().split('\n').filter(l => l.trim());
      return lines[lines.length - 1];
    }
    const match = content.match(new RegExp(this.extractAnswerPattern));
    return match?.[1];
  }

  private formatSolutions(solutions: RSASolution[]): string {
    return solutions.map((sol, i) =>
      `### Solution ${i + 1}\n${sol.reasoningChain}${sol.finalAnswer ? `\n\n**Final Answer**: ${sol.finalAnswer}` : ''}`
    ).join('\n\n');
  }

  async execute<T>(fn: () => Promise<T>): Promise<any> {
    this.metrics = this.initMetrics();

    // Step 1: Generate initial population
    const initialTasks = Array.from({ length: this.populationSize }, () => fn());
    const initialResults = await Promise.allSettled(initialTasks);

    let population: RSASolution[] = initialResults
      .filter((r): r is PromiseFulfilledResult<T> => r.status === 'fulfilled')
      .map(r => {
        const content = typeof r.value === 'string' ? r.value : JSON.stringify(r.value);
        return {
          reasoningChain: content,
          finalAnswer: this.extractAnswer(content),
          rawOutput: r.value as any,
        };
      });

    this.metrics.generationCalls = this.populationSize;
    this.metrics.totalApiCalls = this.populationSize;

    if (population.length === 0) {
      throw new Error('RSA: Failed to generate any initial solutions');
    }

    // Step 2: Iterative refinement
    // Note: In JS SDK, we don't have access to the agent for aggregation
    // This is a simplified version that does voting on the initial population
    // Full aggregation would require passing the agent context

    // For JS SDK, we skip iterations and go straight to voting
    // (Full implementation would require agent-aware execution)
    this.metrics.iterationsCompleted = 0;

    // Step 3: Select final answer
    if (this.selection === 'all') {
      return {
        solutions: population.map(s => s.rawOutput),
        count: population.length,
        _rsaMetrics: this.metrics,
      };
    }

    if (this.selection === 'last_iteration') {
      return population[0].rawOutput;
    }

    // Majority vote
    const votes = new Map<string, { solution: RSASolution; count: number }>();
    for (const sol of population) {
      const key = sol.finalAnswer ?? '';
      const entry = votes.get(key) ?? { solution: sol, count: 0 };
      entry.count++;
      votes.set(key, entry);
    }

    const winner = [...votes.values()].sort((a, b) => b.count - a.count)[0];
    this.metrics.selectionConfidence = winner ? winner.count / population.length : 0;

    const uniqueAnswers = new Set(population.map(s => s.finalAnswer).filter(Boolean)).size;
    this.metrics.finalPopulationDiversity = uniqueAnswers / population.length;

    return {
      ...winner?.solution.rawOutput,
      _rsaMetrics: this.metrics,
    };
  }

  getMetrics(): RSAMetrics {
    return { ...this.metrics };
  }
}

export function getExecutionType(config?: ExecutionConfig): ExecutionType {
  if (config?.type === 'retry') return new RetryExecution(config.backoffs, config.jitter);
  if (config?.type === 'parallel') return new ParallelExecution(config.n_samples ?? 3);
  if (config?.type === 'mdap_voting') return new MDAPVotingExecution(config.k_margin ?? 3, config.max_candidates ?? 10);
  if (config?.type === 'rsa') {
    return new RSAExecution(
      config.population_size ?? 16,
      config.aggregation_k ?? 4,
      config.iterations ?? 5,
      (config.selection as any) ?? 'majority_vote',
      config.aggregation_prompt,
      config.extract_answer,
    );
  }
  return new DefaultExecution();
}
```

### 5.2 Update `sdk/js/src/types.ts`

```typescript
export interface ExecutionConfig {
  type: 'default' | 'retry' | 'parallel' | 'mdap_voting' | 'rsa';

  // Retry
  backoffs?: number[];
  jitter?: number;

  // Parallel
  n_samples?: number;

  // MDAP Voting
  k_margin?: number;
  max_candidates?: number;

  // RSA
  population_size?: number;
  aggregation_k?: number;
  iterations?: number;
  selection?: 'majority_vote' | 'last_iteration' | 'best_reasoning' | 'all';
  aggregator?: string;
  aggregation_prompt?: string;
  extract_answer?: string;
}
```

---

## 6. Configuration Examples

### 6.1 Basic RSA Usage

```yaml
# sdk/examples/rsa_demo/config/machine.yml
spec: flatmachine
spec_version: "0.8.1"

data:
  name: rsa_math_solver

  context:
    problem: "{{ input.problem }}"

  agents:
    solver: ./solver.yml

  states:
    start:
      type: initial
      transitions:
        - to: solve

    solve:
      agent: solver
      execution:
        type: rsa
        population_size: 16
        aggregation_k: 4
        iterations: 5
        selection: majority_vote
      input:
        problem: "{{ context.problem }}"
      output_to_context:
        solution: "{{ output }}"
      transitions:
        - to: done

    done:
      type: final
      output:
        solution: "{{ context.solution }}"

metadata:
  description: "Math problem solver using RSA"
```

### 6.2 Solver Agent

```yaml
# sdk/examples/rsa_demo/config/solver.yml
spec: flatagent
spec_version: "0.8.1"

data:
  name: math-solver

  model:
    profile: default
    temperature: 0.7  # Higher temperature for diversity

  system: |
    You are a mathematical problem solver. Approach problems systematically:
    1. Understand the problem
    2. Identify relevant concepts
    3. Plan your approach
    4. Execute step by step
    5. Verify your answer

    Show your complete reasoning chain.

  user: |
    Solve this problem:

    {{ input.problem }}

    Show your work step by step, then state your final answer clearly.

  output:
    reasoning:
      type: str
      description: "Step-by-step solution"
    answer:
      type: str
      description: "Final answer"

metadata:
  description: "Mathematical problem solver"
```

### 6.3 Advanced RSA with Custom Aggregator

```yaml
# sdk/examples/rsa_advanced/config/machine.yml
spec: flatmachine
spec_version: "0.8.1"

data:
  name: rsa_code_generator

  context:
    task: "{{ input.task }}"
    language: "{{ input.language | default('python') }}"

  agents:
    coder: ./coder.yml

  states:
    start:
      type: initial
      transitions:
        - to: generate

    generate:
      agent: coder
      execution:
        type: rsa
        population_size: 8
        aggregation_k: 3
        iterations: 3
        selection: best_reasoning
        extract_answer: "```(?:python|javascript|typescript)?\n([\\s\\S]*?)```"
        aggregation_prompt: |
          You are reviewing {k} code solutions. Analyze each for:
          - Correctness
          - Efficiency
          - Code quality
          - Error handling

          ## Task
          {original_prompt}

          ## Solutions
          {solutions_text}

          Synthesize the best solution, combining strengths from each.
      input:
        task: "{{ context.task }}"
        language: "{{ context.language }}"
      output_to_context:
        code: "{{ output }}"
      transitions:
        - to: done

    done:
      type: final
      output:
        code: "{{ context.code }}"
```

### 6.4 RSA with Retry Fallback

```yaml
# Combining RSA with retry for robustness
states:
  solve:
    agent: solver
    execution:
      type: rsa
      population_size: 16
      aggregation_k: 4
      iterations: 5
    on_error:
      default: retry_solve  # Fallback to simple retry
    input:
      problem: "{{ context.problem }}"
    transitions:
      - to: done

  retry_solve:
    agent: solver
    execution:
      type: retry
      backoffs: [2, 4, 8]
    input:
      problem: "{{ context.problem }}"
    transitions:
      - to: done
```

---

## 7. Testing Strategy

### 7.1 Unit Tests

```python
# sdk/python/tests/unit/test_rsa.py

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

from flatagents.rsa import RSAExecution, Solution, RSAMetrics


class TestRSAExecution:
    """Unit tests for RSAExecution."""

    def test_from_config_defaults(self):
        """Test default configuration."""
        config = {"type": "rsa"}
        rsa = RSAExecution.from_config(config)

        assert rsa.population_size == 16
        assert rsa.aggregation_k == 4
        assert rsa.iterations == 5
        assert rsa.selection == "majority_vote"

    def test_from_config_custom(self):
        """Test custom configuration."""
        config = {
            "type": "rsa",
            "population_size": 8,
            "aggregation_k": 2,
            "iterations": 3,
            "selection": "last_iteration"
        }
        rsa = RSAExecution.from_config(config)

        assert rsa.population_size == 8
        assert rsa.aggregation_k == 2
        assert rsa.iterations == 3
        assert rsa.selection == "last_iteration"

    def test_extract_answer_default(self):
        """Test default answer extraction."""
        rsa = RSAExecution()
        content = "Step 1: ...\nStep 2: ...\nFinal Answer: 42"

        answer = rsa._extract_answer(content)
        assert answer == "Final Answer: 42"

    def test_extract_answer_regex(self):
        """Test regex answer extraction."""
        rsa = RSAExecution(extract_answer=r"Answer:\s*(\d+)")
        content = "The answer is Answer: 42 done."

        answer = rsa._extract_answer(content)
        assert answer == "42"

    def test_format_solutions(self):
        """Test solution formatting for aggregation."""
        rsa = RSAExecution()
        solutions = [
            Solution("Step 1...", "42"),
            Solution("Step A...", "43"),
        ]

        formatted = rsa._format_solutions_for_aggregation(solutions)

        assert "### Solution 1" in formatted
        assert "### Solution 2" in formatted
        assert "Step 1..." in formatted
        assert "**Final Answer**: 42" in formatted

    def test_select_final_majority_vote(self):
        """Test majority vote selection."""
        rsa = RSAExecution(selection="majority_vote")
        population = [
            Solution("...", "42"),
            Solution("...", "42"),
            Solution("...", "42"),
            Solution("...", "43"),
            Solution("...", "44"),
        ]

        result = rsa._select_final(population)

        assert result is not None
        assert rsa.metrics.selection_confidence == 0.6  # 3/5

    def test_select_final_all(self):
        """Test 'all' selection strategy."""
        rsa = RSAExecution(selection="all")
        population = [
            Solution("A", "1", {"content": "A"}),
            Solution("B", "2", {"content": "B"}),
        ]

        result = rsa._select_final(population)

        assert result["count"] == 2
        assert len(result["solutions"]) == 2

    @pytest.mark.asyncio
    async def test_execute_full_flow(self):
        """Test full RSA execution flow."""
        rsa = RSAExecution(
            population_size=4,
            aggregation_k=2,
            iterations=2
        )

        # Mock agent
        agent = MagicMock()
        call_count = 0

        async def mock_call(**kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            result.output = {"content": f"Solution {call_count}"}
            result.content = f"Final answer: {call_count % 2}"
            return result

        agent.call = mock_call

        result = await rsa.execute(agent, {"problem": "test"})

        assert result is not None
        assert "_rsa_metrics" in result

        metrics = result["_rsa_metrics"]
        assert metrics["population_size"] == 4
        assert metrics["iterations_completed"] == 2
        # 4 initial + 2 iterations * 4 = 12 calls
        assert metrics["total_api_calls"] == 12


class TestSolution:
    """Tests for Solution dataclass."""

    def test_solution_hash_with_answer(self):
        """Solutions with same answer should hash equal."""
        s1 = Solution("Different chain 1", "42")
        s2 = Solution("Different chain 2", "42")

        assert hash(s1) == hash(s2)

    def test_solution_hash_without_answer(self):
        """Solutions without answer use chain prefix."""
        s1 = Solution("Same prefix..." + "A" * 100, None)
        s2 = Solution("Same prefix..." + "B" * 100, None)

        # First 100 chars same, so hash equal
        assert hash(s1) == hash(s2)
```

### 7.2 Integration Tests

```python
# sdk/python/tests/integration/test_rsa_integration.py

import pytest
import os

from flatagents import FlatMachine


@pytest.mark.integration
class TestRSAIntegration:
    """Integration tests for RSA with real LLM calls."""

    @pytest.fixture
    def rsa_machine_config(self, tmp_path):
        """Create a minimal RSA machine config."""
        config = tmp_path / "machine.yml"
        config.write_text("""
spec: flatmachine
spec_version: "0.8.1"
data:
  name: test_rsa
  agents:
    solver:
      spec: flatagent
      spec_version: "0.8.1"
      data:
        model: { provider: openai, name: gpt-4o-mini }
        system: "Solve math problems. Always end with 'Answer: X'"
        user: "{{ input.problem }}"
  states:
    start:
      type: initial
      transitions:
        - to: solve
    solve:
      agent: solver
      execution:
        type: rsa
        population_size: 4
        aggregation_k: 2
        iterations: 1
        extract_answer: "Answer:\\s*(\\d+)"
      input:
        problem: "{{ input.problem }}"
      output_to_context:
        result: "{{ output }}"
      transitions:
        - to: done
    done:
      type: final
      output:
        result: "{{ context.result }}"
""")
        return str(config)

    @pytest.mark.skipif(
        not os.environ.get("OPENAI_API_KEY"),
        reason="OPENAI_API_KEY not set"
    )
    async def test_rsa_simple_math(self, rsa_machine_config):
        """Test RSA on simple math problem."""
        machine = FlatMachine.from_file(rsa_machine_config)

        result = await machine.execute({
            "problem": "What is 15 + 27? Show your work."
        })

        assert result is not None
        assert "42" in str(result) or "result" in result
```

### 7.3 Performance Benchmarks

```python
# sdk/python/tests/benchmarks/bench_rsa.py

import pytest
import time
from unittest.mock import MagicMock, AsyncMock

from flatagents.rsa import RSAExecution


class TestRSAPerformance:
    """Performance benchmarks for RSA."""

    @pytest.mark.benchmark
    async def test_rsa_api_call_count(self):
        """Verify expected API call counts."""
        configs = [
            {"N": 4, "K": 2, "T": 2, "expected_calls": 4 + 4*2},   # 12
            {"N": 8, "K": 4, "T": 3, "expected_calls": 8 + 8*3},   # 32
            {"N": 16, "K": 4, "T": 5, "expected_calls": 16 + 16*5}, # 96
            {"N": 16, "K": 4, "T": 10, "expected_calls": 16 + 16*10}, # 176
        ]

        for cfg in configs:
            rsa = RSAExecution(
                population_size=cfg["N"],
                aggregation_k=cfg["K"],
                iterations=cfg["T"]
            )

            agent = MagicMock()
            agent.call = AsyncMock(return_value=MagicMock(
                output={"content": "test"},
                content="Answer: 42"
            ))

            await rsa.execute(agent, {"problem": "test"})

            assert rsa.metrics.total_api_calls == cfg["expected_calls"], \
                f"N={cfg['N']}, K={cfg['K']}, T={cfg['T']}: " \
                f"expected {cfg['expected_calls']}, got {rsa.metrics.total_api_calls}"
```

---

## 8. Implementation Phases

### Phase 1: Core Implementation (Week 1-2)

| Task | Status | Files |
|------|--------|-------|
| Create `rsa.py` with RSAExecution class | TODO | `sdk/python/flatagents/rsa.py` |
| Update `flatmachine.d.ts` spec | TODO | `flatmachine.d.ts` |
| Update Python `execution.py` import | TODO | `sdk/python/flatagents/execution.py` |
| Update Python `__init__.py` exports | TODO | `sdk/python/flatagents/__init__.py` |
| Add unit tests | TODO | `sdk/python/tests/unit/test_rsa.py` |

### Phase 2: JavaScript SDK (Week 2)

| Task | Status | Files |
|------|--------|-------|
| Update `execution.ts` with RSAExecution | TODO | `sdk/js/src/execution.ts` |
| Update `types.ts` with RSA config | TODO | `sdk/js/src/types.ts` |
| Add JS tests | TODO | `sdk/js/tests/execution.test.ts` |

### Phase 3: Examples & Documentation (Week 3)

| Task | Status | Files |
|------|--------|-------|
| Create `rsa_demo` example | TODO | `sdk/examples/rsa_demo/` |
| Create `rsa_code_gen` example | TODO | `sdk/examples/rsa_code_gen/` |
| Update MACHINES.md | TODO | `MACHINES.md` |
| Update CLAUDE.md | TODO | `CLAUDE.md` |

### Phase 4: Integration Tests & Polish (Week 4)

| Task | Status | Files |
|------|--------|-------|
| Integration tests with real LLMs | TODO | `sdk/python/tests/integration/` |
| Performance benchmarks | TODO | `sdk/python/tests/benchmarks/` |
| Edge case handling | TODO | Various |
| Metrics dashboard integration | TODO | `sdk/python/flatagents/monitoring.py` |

---

## Appendix A: RSA vs Existing Execution Types

| Feature | default | parallel | retry | mdap_voting | **rsa** |
|---------|---------|----------|-------|-------------|---------|
| API Calls | 1 | N | 1-N | 1-K | N*(1+T) |
| Diversity | None | High | None | Medium | High (preserved) |
| Self-Improvement | No | No | No | No | **Yes** |
| Cross-referencing | No | No | No | No | **Yes** |
| Use Case | Simple | Variety | Robustness | Consensus | **Hard reasoning** |

## Appendix B: Performance Considerations

### B.1 API Call Scaling

```
Total Calls = N * (1 + T)

Examples:
- N=4, T=2:  4*(1+2)  = 12 calls
- N=8, T=5:  8*(1+5)  = 48 calls
- N=16, T=5: 16*(1+5) = 96 calls
- N=16, T=10: 16*(1+10) = 176 calls
```

### B.2 Latency Optimization

- Initial generation: Fully parallel
- Each iteration: Fully parallel
- Overall latency ≈ (1 + T) * single_call_latency

### B.3 Cost Optimization

- Use smaller/faster models for initial generation
- Use stronger models for aggregation (optional)
- Early stopping when population converges

## Appendix C: References

1. [arXiv:2509.26626](https://arxiv.org/abs/2509.26626) - Original RSA Paper
2. [RSA Project Page](https://rsa-llm.github.io/) - Implementation Details
3. [GitHub: HyperPotatoNeo/RSA](https://github.com/HyperPotatoNeo/RSA) - Reference Code
4. [OpenReview](https://openreview.net/forum?id=J7upvGcP9h) - Peer Review Discussion
