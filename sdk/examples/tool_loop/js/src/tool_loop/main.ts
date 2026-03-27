#!/usr/bin/env node
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  FlatAgent,
  MockLLMBackend,
  setupLogging,
  getLogger,
  StopReason,
  ToolLoopAgent,
} from '@memgrafter/flatagents';
import type { Guardrails, MockResponse } from '@memgrafter/flatagents';
import { ALL_TOOLS } from './tools.js';

setupLogging({ level: 'INFO' });
const logger = getLogger(import.meta.url);

const DEFAULT_QUESTION = "What's the weather in Tokyo and the current time there?";

type Args = {
  question: string;
  mock: boolean;
};

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const configPath = join(__dirname, '..', '..', '..', 'config', 'agent.yml');

function parseArgs(argv: string[]): Args {
  if (argv.includes('--help') || argv.includes('-h')) {
    printUsage();
    process.exit(0);
  }

  const mock = argv.includes('--mock');
  const questionParts = argv.filter((arg) => !arg.startsWith('--'));

  return {
    mock,
    question: questionParts.length > 0 ? questionParts.join(' ') : DEFAULT_QUESTION,
  };
}

function printUsage(): void {
  console.log([
    'Tool Loop Example — FlatAgents JS',
    '',
    'Usage:',
    '  node dist/tool_loop/main.js',
    '  node dist/tool_loop/main.js "What time is it in Tokyo?"',
    '  node dist/tool_loop/main.js --mock "Weather in London and time in UTC"',
  ].join('\n'));
}

function buildMockResponses(): MockResponse[] {
  return [
    {
      content: 'I will check weather first.',
      raw: {
        text: 'I will check weather first.',
        finishReason: 'tool_calls',
        toolCalls: [
          {
            toolCallId: 'call_weather_1',
            toolName: 'get_weather',
            args: { city: 'Tokyo' },
          },
        ],
        usage: {
          promptTokens: 40,
          completionTokens: 16,
          totalTokens: 56,
        },
      },
    },
    {
      content: 'Now I will check the time.',
      raw: {
        text: 'Now I will check the time.',
        finishReason: 'tool_calls',
        toolCalls: [
          {
            toolCallId: 'call_time_1',
            toolName: 'get_time',
            args: { timezone: 'Asia/Tokyo' },
          },
        ],
        usage: {
          promptTokens: 52,
          completionTokens: 18,
          totalTokens: 70,
        },
      },
    },
    {
      content: 'In Tokyo it is partly cloudy at about 68°F, and I also looked up the local time.',
      raw: {
        text: 'In Tokyo it is partly cloudy at about 68°F, and I also looked up the local time.',
        finishReason: 'stop',
        usage: {
          promptTokens: 66,
          completionTokens: 24,
          totalTokens: 90,
        },
      },
    },
  ];
}

async function run(question: string, useMock: boolean): Promise<void> {
  logger.info('--- Starting ToolLoopAgent Demo ---');
  logger.info(`Question: ${question}`);

  const agent = useMock
    ? new FlatAgent({
        config: configPath,
        llmBackend: new MockLLMBackend(buildMockResponses()),
      })
    : new FlatAgent(configPath);

  const guardrails: Guardrails = {
    max_turns: 5,
    max_tool_calls: 10,
    tool_timeout: 10,
    total_timeout: 60,
  };

  const loop = new ToolLoopAgent({
    agent,
    tools: ALL_TOOLS,
    guardrails,
  });

  const result = await loop.run({ question });

  logger.info('--- Execution Complete ---');
  logger.info(`Stop reason : ${result.stop_reason}`);
  logger.info(`Turns       : ${result.turns}`);
  logger.info(`Tool calls  : ${result.tool_calls_count}`);
  logger.info(`API calls   : ${result.usage.api_calls}`);
  logger.info(`Total tokens: ${result.usage.total_tokens}`);
  logger.info(`Total cost  : $${result.usage.total_cost.toFixed(6)}`);

  if (result.error) {
    logger.error(`Error: ${result.error}`);
  }

  console.log();
  console.log('=== Answer ===');
  console.log(result.content ?? '(no content)');
  console.log();

  if (result.stop_reason !== StopReason.COMPLETE) {
    logger.warning(`Loop did not complete normally (reason: ${result.stop_reason})`);
  }
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));
  await run(args.question, args.mock);
}

main().catch((error) => {
  logger.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
