import { join } from 'path';
import { DataGenerator } from './data_generator.js';
import { JudgeEvaluator, EvaluationResult } from './evaluator.js';
import { PromptEvolver } from './prompt_evolver.js';
import { loadYaml, saveYaml, loadJson, saveJson, loadAgent, createLogger } from './utils.js';
import type { AgentConfig } from '@memgrafter/flatagents';
import { RUN_LENGTH_DEFAULTS } from './run_length.js';

export type OptimizationConfig = {
  budget: number;
  pareto_set_size: number;
  minibatch_size: number;
  test_split: number;
  early_stop_patience: number;
  verbose?: boolean;
};

export type Candidate = {
  id: number;
  config: AgentConfig;
  parent_id: number | null;
  scores: Record<number, number>;
};

export type IterationResult = {
  iteration: number;
  parent_id: number;
  child_id: number | null;
  parent_minibatch_score: number;
  child_minibatch_score: number | null;
  promoted: boolean;
  child_pareto_avg: number | null;
};

export type OptimizationResult = {
  start_time: string;
  end_time: string;
  initial_accuracy: number;
  final_accuracy: number;
  total_improvement: number;
  iterations: IterationResult[];
  final_config: AgentConfig;
  best_candidate_id: number;
  best_lineage: number[];
  population_size: number;
  total_llm_calls: number;
  total_cost: number;
  toDict: () => Record<string, any>;
};

class Population {
  candidates: Candidate[] = [];
  pareto_scores: Record<number, Record<number, number>> = {};

  addCandidate(candidate: Candidate, scores: Record<number, number>) {
    this.candidates.push(candidate);
    this.pareto_scores[candidate.id] = scores;
    candidate.scores = scores;
  }
}

class AncestryTree {
  parents: Record<number, number | null> = {};

  add(candidateId: number, parentId: number | null) {
    this.parents[candidateId] = parentId;
  }

  getLineage(candidateId: number): number[] {
    const lineage: number[] = [];
    let current: number | null = candidateId;
    while (current !== null) {
      lineage.push(current);
      current = this.parents[current] ?? null;
    }
    return lineage.reverse();
  }

  getDepth(candidateId: number): number {
    return this.getLineage(candidateId).length - 1;
  }
}

export class GEPASelfOptimizer {
  private config: OptimizationConfig;
  private dataGenerator: DataGenerator;
  private promptEvolver: PromptEvolver;
  private summaryGenerator;
  private currentJudgeConfig: AgentConfig;
  private dataDir: string;
  private logger;
  private verbose: boolean;
  private population = new Population();
  private ancestry = new AncestryTree();
  private iterations: IterationResult[] = [];
  private totalLlmCalls = 0;
  private totalCost = 0;

  constructor(
    private configDir: string,
    private outputDir: string,
    config?: Partial<OptimizationConfig>,
  ) {
    this.verbose = config?.verbose ?? true;
    this.logger = createLogger(this.verbose);
    this.config = {
      budget: config?.budget ?? RUN_LENGTH_DEFAULTS.budget,
      pareto_set_size: config?.pareto_set_size ?? RUN_LENGTH_DEFAULTS.pareto_set_size,
      minibatch_size: config?.minibatch_size ?? RUN_LENGTH_DEFAULTS.minibatch_size,
      test_split: config?.test_split ?? RUN_LENGTH_DEFAULTS.test_split,
      early_stop_patience: config?.early_stop_patience ?? RUN_LENGTH_DEFAULTS.early_stop_patience,
    };

    this.dataGenerator = new DataGenerator(configDir, { verbose: this.verbose });
    this.promptEvolver = new PromptEvolver(configDir, { verbose: this.verbose });
    this.summaryGenerator = loadAgent(join(configDir, 'agents', 'summary_generator.yml'));
    this.currentJudgeConfig = loadYaml(join(configDir, 'agents', 'judge.yml')) as AgentConfig;
    this.dataDir = join(configDir, '..', 'data');
    this.logger.info('GEPASelfOptimizer initialized with GEPA algorithm');
  }

  async generateData(numExamples = 100, forceRegenerate = false): Promise<Array<Record<string, any>>> {
    const dataPath = join(this.dataDir, 'evaluation_set.json');
    if (!forceRegenerate) {
      try {
        this.logger.info(`Loading existing data from ${dataPath}`);
        return loadJson<Array<Record<string, any>>>(dataPath);
      } catch {
        // fallthrough
      }
    }

    this.logger.info(`Generating ${numExamples} evaluation examples`);
    const examples = await this.dataGenerator.generateDataset(numExamples);
    saveJson(examples, dataPath);
    return examples;
  }

  splitData(examples: Array<Record<string, any>>): [Array<Record<string, any>>, Array<Record<string, any>>, Array<Record<string, any>>] {
    const n = examples.length;
    const nPareto = Math.min(this.config.pareto_set_size, Math.floor(n / 3));
    const nTest = Math.floor(n * this.config.test_split);

    const shuffled = [...examples].sort(() => Math.random() - 0.5);
    const dTest = shuffled.slice(0, nTest);
    const dPareto = shuffled.slice(nTest, nTest + nPareto);
    const dFeedback = shuffled.slice(nTest + nPareto);

    return [dFeedback, dPareto, dTest];
  }

  private dominates(aId: number, bId: number, nInstances: number): boolean {
    let dominated = true;
    let strictlyBetter = false;

    for (let i = 0; i < nInstances; i += 1) {
      const aScore = this.population.pareto_scores[aId]?.[i] ?? 0;
      const bScore = this.population.pareto_scores[bId]?.[i] ?? 0;
      if (aScore < bScore) {
        dominated = false;
        break;
      }
      if (aScore > bScore) {
        strictlyBetter = true;
      }
    }

    return dominated && strictlyBetter;
  }

  selectCandidate(dPareto: Array<Record<string, any>>): number {
    if (this.population.candidates.length === 1) {
      return this.population.candidates[0].id;
    }

    const nInstances = dPareto.length;
    const bestPerInstance: Record<number, number[]> = {};

    for (let i = 0; i < nInstances; i += 1) {
      let bestScore = -Infinity;
      let bestCandidates: number[] = [];
      for (const candidate of this.population.candidates) {
        const score = this.population.pareto_scores[candidate.id]?.[i] ?? 0;
        if (score > bestScore) {
          bestScore = score;
          bestCandidates = [candidate.id];
        } else if (score === bestScore) {
          bestCandidates.push(candidate.id);
        }
      }
      bestPerInstance[i] = bestCandidates;
    }

    const frontier = new Set<number>();
    Object.values(bestPerInstance).forEach(ids => ids.forEach(id => frontier.add(id)));

    const nonDominated = new Set<number>(frontier);
    frontier.forEach(aId => {
      frontier.forEach(bId => {
        if (aId === bId) return;
        if (this.dominates(aId, bId, nInstances)) {
          nonDominated.delete(bId);
        }
      });
    });

    const candidates = Array.from(nonDominated.size ? nonDominated : frontier);
    const frequency: Record<number, number> = Object.fromEntries(candidates.map(id => [id, 0]));
    Object.values(bestPerInstance).forEach(ids => {
      ids.forEach(id => {
        if (id in frequency) {
          frequency[id] += 1;
        }
      });
    });

    const total = Object.values(frequency).reduce((sum, value) => sum + value, 0);
    if (total === 0) {
      return candidates[Math.floor(Math.random() * candidates.length)];
    }

    let pick = Math.random() * total;
    for (const id of candidates) {
      pick -= frequency[id];
      if (pick <= 0) {
        return id;
      }
    }

    return candidates[0];
  }

  async evaluateOnPareto(config: AgentConfig, dPareto: Array<Record<string, any>>): Promise<Record<number, number>> {
    const evaluator = new JudgeEvaluator({ judgeConfigDict: config, verbose: this.verbose });
    const scores: Record<number, number> = {};

    for (let i = 0; i < dPareto.length; i += 1) {
      const prediction = await evaluator.evaluateSingle(dPareto[i]);
      const output = prediction.output ?? {};
      const expected = dPareto[i].expected_verdict ?? 'PASS';
      const predicted = output.verdict ?? 'PASS';
      scores[i] = predicted === expected ? 1.0 : 0.0;
    }

    return scores;
  }

  private gatherTraces(examples: Array<Record<string, any>>, result: EvaluationResult): Array<Record<string, any>> {
    return examples.map((example, index) => {
      const prediction = result.predictions[index] ?? {};
      const expected = example.expected_verdict ?? 'PASS';
      const predicted = prediction.verdict ?? 'PASS';
      return {
        input: {
          task: example.task ?? '',
          response: example.agent_response ?? '',
        },
        output: {
          verdict: predicted,
          reasoning: prediction.reasoning ?? '',
        },
        feedback: predicted === expected ? 'CORRECT' : `INCORRECT: expected ${expected}, got ${predicted}`,
        correct_verdict: expected,
      };
    });
  }

  async runIteration(iteration: number, dFeedback: Array<Record<string, any>>, dPareto: Array<Record<string, any>>): Promise<IterationResult> {
    const parentId = this.selectCandidate(dPareto);
    const parent = this.population.candidates.find(candidate => candidate.id === parentId)!;
    this.logger.info(`Selected parent candidate ${parentId} for mutation`);

    const minibatchSize = Math.min(this.config.minibatch_size, dFeedback.length);
    const minibatch = [...dFeedback].sort(() => Math.random() - 0.5).slice(0, minibatchSize);

    const parentEvaluator = new JudgeEvaluator({ judgeConfigDict: parent.config, verbose: this.verbose });
    const parentResult = await parentEvaluator.evaluateDataset(minibatch, false);
    const parentScore = parentResult.accuracy;
    this.logger.info(`Parent score on minibatch: ${parentScore.toFixed(1)}%`);

    if (!parentResult.failures.length) {
      this.logger.info('Parent perfect on minibatch, skipping mutation');
      return {
        iteration,
        parent_id: parentId,
        child_id: null,
        parent_minibatch_score: parentScore,
        child_minibatch_score: null,
        promoted: false,
        child_pareto_avg: null,
      };
    }

    const traces = this.gatherTraces(minibatch, parentResult);
    const candidatePrompt = await this.promptEvolver.reflectiveUpdate(parent.config, traces);
    const childConfig = this.promptEvolver.createCandidateConfig(parent.config, candidatePrompt);

    const childEvaluator = new JudgeEvaluator({ judgeConfigDict: childConfig, verbose: this.verbose });
    const childResult = await childEvaluator.evaluateDataset(minibatch, false);
    const childScore = childResult.accuracy;
    this.logger.info(`Child score on minibatch: ${childScore.toFixed(1)}%`);

    if (childScore <= parentScore) {
      this.logger.info(
        `Child (${childScore.toFixed(1)}%) did not improve on parent (${parentScore.toFixed(1)}%) - not promoting`,
      );
      return {
        iteration,
        parent_id: parentId,
        child_id: null,
        parent_minibatch_score: parentScore,
        child_minibatch_score: childScore,
        promoted: false,
        child_pareto_avg: null,
      };
    }

    this.logger.info(
      `Child improved: ${parentScore.toFixed(1)}% -> ${childScore.toFixed(1)}% - promoting to population`,
    );

    const childParetoScores = await this.evaluateOnPareto(childConfig, dPareto);
    const childParetoAvg = (Object.values(childParetoScores).reduce((sum, value) => sum + value, 0) / dPareto.length) * 100;

    const childId = this.population.candidates.length;
    const child: Candidate = {
      id: childId,
      config: childConfig,
      parent_id: parentId,
      scores: childParetoScores,
    };

    this.population.addCandidate(child, childParetoScores);
    this.ancestry.add(childId, parentId);
    this.logger.info(
      `Added candidate ${childId} to population (depth ${this.ancestry.getDepth(childId)}, pareto avg ${childParetoAvg.toFixed(1)}%)`,
    );

    return {
      iteration,
      parent_id: parentId,
      child_id: childId,
      parent_minibatch_score: parentScore,
      child_minibatch_score: childScore,
      promoted: true,
      child_pareto_avg: childParetoAvg,
    };
  }

  private getBestCandidateId(): number {
    let bestId = 0;
    let bestAvg = -Infinity;

    for (const candidate of this.population.candidates) {
      const scores = this.population.pareto_scores[candidate.id];
      if (!scores) continue;
      const avg = Object.values(scores).reduce((sum, value) => sum + value, 0) / Object.keys(scores).length;
      if (avg > bestAvg) {
        bestAvg = avg;
        bestId = candidate.id;
      }
    }

    return bestId;
  }

  private async generateSummary(result: OptimizationResult): Promise<void> {
    const promoted = result.iterations.filter(iteration => iteration.promoted);
    const summaryResult = await this.summaryGenerator.call({
      num_iterations: result.iterations.length,
      total_calls: result.total_llm_calls,
      num_examples: this.population.candidates.length,
      iterations: promoted.slice(0, 10).map(iteration => ({
        iteration: iteration.iteration,
        promoted: iteration.promoted,
        pareto_avg: iteration.child_pareto_avg,
      })),
      start_accuracy: result.initial_accuracy,
      final_accuracy: result.final_accuracy,
      improvement: result.total_improvement,
      key_changes: promoted.slice(0, 5).map(iteration => `Candidate ${iteration.child_id} from parent ${iteration.parent_id}`),
    });

    const summaryOutput = summaryResult.output ?? {};
    saveJson(summaryOutput, join(this.outputDir, 'summary.json'));
    const summaryText = typeof summaryOutput.summary === 'string' ? summaryOutput.summary : '';
    this.logger.info(`Summary: ${summaryText}`);
  }

  private updateTotals(): void {
    const genStats = this.dataGenerator.getStats();
    const evolverStats = this.promptEvolver.getStats();

    this.totalLlmCalls += genStats.task_generator_calls + genStats.response_generator_calls;
    this.totalLlmCalls += evolverStats.reflective_updater_calls;
    this.totalCost += genStats.task_generator_cost + genStats.response_generator_cost;
    this.totalCost += evolverStats.reflective_updater_cost;
    this.totalLlmCalls += 1; // summary call
  }

  async optimize(numExamples = RUN_LENGTH_DEFAULTS.num_examples, forceRegenerateData = false): Promise<OptimizationResult> {
    const startTime = new Date().toISOString();
    const examples = await this.generateData(numExamples, forceRegenerateData);
    const [dFeedback, dPareto, dTest] = this.splitData(examples);
    this.logger.info(`Data split: ${dFeedback.length} feedback, ${dPareto.length} pareto, ${dTest.length} test`);

    const baseScores = await this.evaluateOnPareto(this.currentJudgeConfig, dPareto);
    const baseCandidate: Candidate = {
      id: 0,
      config: this.currentJudgeConfig,
      parent_id: null,
      scores: baseScores,
    };

    this.population.addCandidate(baseCandidate, baseScores);
    this.ancestry.add(0, null);
    const initialParetoAvg = (Object.values(baseScores).reduce((sum, value) => sum + value, 0) / dPareto.length) * 100;
    this.logger.info(`Base system average score on D_pareto: ${initialParetoAvg.toFixed(1)}%`);

    const initialEvaluator = new JudgeEvaluator({ judgeConfigDict: this.currentJudgeConfig, verbose: this.verbose });
    const initialResult = await initialEvaluator.evaluateDataset(dTest, false);
    const initialAccuracy = initialResult.accuracy;
    this.logger.info(`Initial test accuracy: ${initialAccuracy.toFixed(1)}%`);

    let noNewCandidates = 0;

    for (let iteration = 1; iteration <= this.config.budget; iteration += 1) {
      this.logger.info(`\n${'='.repeat(60)}\nIteration ${iteration}/${this.config.budget}\n${'='.repeat(60)}`);
      this.logger.info(`Population size: ${this.population.candidates.length}`);
      const result = await this.runIteration(iteration, dFeedback, dPareto);
      this.iterations.push(result);

      if (result.promoted) {
        noNewCandidates = 0;
      } else {
        noNewCandidates += 1;
        if (noNewCandidates >= this.config.early_stop_patience) {
          this.logger.info(`Early stopping: no new candidates for ${noNewCandidates} iterations`);
          break;
        }
      }
    }

    const bestId = this.getBestCandidateId();
    const bestCandidate = this.population.candidates.find(candidate => candidate.id === bestId)!;
    const bestLineage = this.ancestry.getLineage(bestId);
    this.logger.info(`\nBest candidate: ${bestId}`);
    this.logger.info(`Lineage: ${JSON.stringify(bestLineage)}`);

    const finalEvaluator = new JudgeEvaluator({ judgeConfigDict: bestCandidate.config, verbose: this.verbose });
    const finalResult = await finalEvaluator.evaluateDataset(dTest, false);
    const finalAccuracy = finalResult.accuracy;
    this.logger.info(`Final test accuracy: ${finalAccuracy.toFixed(1)}%`);
    this.logger.info(`Total improvement: ${(finalAccuracy - initialAccuracy).toFixed(1)}%`);

    this.updateTotals();

    saveYaml(bestCandidate.config, join(this.outputDir, 'optimized_judge.yml'));
    this.logger.info(`Saved optimized judge to ${join(this.outputDir, 'optimized_judge.yml')}`);

    const endTime = new Date().toISOString();

    const optimizationResult: OptimizationResult = {
      start_time: startTime,
      end_time: endTime,
      initial_accuracy: initialAccuracy,
      final_accuracy: finalAccuracy,
      total_improvement: finalAccuracy - initialAccuracy,
      iterations: this.iterations,
      final_config: bestCandidate.config,
      best_candidate_id: bestId,
      best_lineage: bestLineage,
      population_size: this.population.candidates.length,
      total_llm_calls: this.totalLlmCalls,
      total_cost: this.totalCost,
      toDict: () => ({
        start_time: startTime,
        end_time: endTime,
        initial_accuracy: initialAccuracy,
        final_accuracy: finalAccuracy,
        total_improvement: finalAccuracy - initialAccuracy,
        num_iterations: this.iterations.length,
        iterations: this.iterations.map(iteration => ({
          iteration: iteration.iteration,
          parent_id: iteration.parent_id,
          child_id: iteration.child_id,
          promoted: iteration.promoted,
          child_pareto_avg: iteration.child_pareto_avg,
        })),
        best_candidate_id: bestId,
        best_lineage: bestLineage,
        population_size: this.population.candidates.length,
        total_llm_calls: this.totalLlmCalls,
        total_cost: this.totalCost,
      }),
    };

    saveJson(optimizationResult.toDict(), join(this.outputDir, 'optimization_log.json'));
    this.logger.info(`Saved optimization log to ${join(this.outputDir, 'optimization_log.json')}`);
    await this.generateSummary(optimizationResult);

    return optimizationResult;
  }
}
