import { loadAgent, loadYaml, createAgentFromDict, calculateAccuracy, calculateFalsePositiveRate, calculateFalseNegativeRate, calculateCalibrationError, createLogger } from './utils.js';
import type { AgentConfig } from '@memgrafter/flatagents';

export class EvaluationResult {
  constructor(
    public accuracy: number,
    public falsePositiveRate: number,
    public falseNegativeRate: number,
    public calibrationError: number,
    public predictions: Array<Record<string, any>>,
    public failures: Array<Record<string, any>>,
    public totalCalls: number,
    public totalCost: number,
  ) {}

  get balancedAccuracy(): number {
    const tpr = 100 - this.falseNegativeRate;
    const tnr = 100 - this.falsePositiveRate;
    return (tpr + tnr) / 2;
  }

  toDict(): Record<string, any> {
    return {
      accuracy: this.accuracy,
      balanced_accuracy: this.balancedAccuracy,
      false_positive_rate: this.falsePositiveRate,
      false_negative_rate: this.falseNegativeRate,
      calibration_error: this.calibrationError,
      num_failures: this.failures.length,
      total_calls: this.totalCalls,
      total_cost: this.totalCost,
    };
  }
}

export class JudgeEvaluator {
  private judge;
  private judgeConfig: AgentConfig;
  private stats = { total_calls: 0, total_cost: 0 };
  private logger;

  constructor(options: { judgeConfigPath?: string; judgeConfigDict?: AgentConfig; verbose?: boolean }) {
    if (options.judgeConfigPath) {
      this.judge = loadAgent(options.judgeConfigPath);
      this.judgeConfig = loadYaml(options.judgeConfigPath) as AgentConfig;
    } else if (options.judgeConfigDict) {
      this.judge = createAgentFromDict(options.judgeConfigDict);
      this.judgeConfig = options.judgeConfigDict;
    } else {
      throw new Error('Must provide judgeConfigPath or judgeConfigDict');
    }
    this.logger = createLogger(options.verbose ?? true);
    this.logger.info('JudgeEvaluator initialized');
  }

  async evaluateSingle(example: Record<string, any>): Promise<Record<string, any>> {
    this.stats.total_calls += 1;
    return this.judge.call({
      task: example.task ?? '',
      response: example.agent_response ?? '',
      context: example.evaluation_criteria ?? '',
    });
  }

  async evaluateDataset(examples: Array<Record<string, any>>, showProgress = true): Promise<EvaluationResult> {
    const predictions: Array<Record<string, any>> = [];
    const failures: Array<Record<string, any>> = [];

    for (let i = 0; i < examples.length; i += 1) {
      if (showProgress) {
        this.logger.info(`Evaluating example ${i + 1}/${examples.length}`);
      }
      const prediction = await this.evaluateSingle(examples[i]);
      const output = prediction.output ?? {};
      predictions.push(output);

      const expected = examples[i].expected_verdict ?? 'PASS';
      const predicted = output.verdict ?? 'PASS';
      if (predicted !== expected) {
        failures.push({
          example: examples[i],
          prediction,
          expected_verdict: expected,
          predicted_verdict: predicted,
        });
      }
    }

    const groundTruth = examples.map(example => ({ expected_verdict: example.expected_verdict ?? 'PASS' }));

    const result = new EvaluationResult(
      calculateAccuracy(predictions, groundTruth),
      calculateFalsePositiveRate(predictions, groundTruth),
      calculateFalseNegativeRate(predictions, groundTruth),
      calculateCalibrationError(predictions, groundTruth),
      predictions,
      failures,
      this.stats.total_calls,
      this.stats.total_cost,
    );

    this.logger.info(`Evaluation complete: accuracy=${result.accuracy.toFixed(1)}%, failures=${failures.length}`);

    return result;
  }

  getPrompts(): { system: string; user: string } {
    const data = this.judgeConfig.data ?? {};
    return { system: data.system ?? '', user: data.user ?? '' };
  }
}
