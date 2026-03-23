#!/usr/bin/env node
import { FlatMachine, MemoryBackend, inMemoryResultBackend } from '@memgrafter/flatmachines';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const rootDir = join(__dirname, '..', '..', '..');
const configDir = join(rootDir, 'config');

async function main() {
  // Set up persistence and result backends for peering
  const persistenceBackend = new MemoryBackend();
  const resultBackend = inMemoryResultBackend;

  console.log('=== Peering Example ===');
  console.log('Launching orchestrator with worker nodes...\n');

  const orchestrator = new FlatMachine({
    config: join(configDir, 'orchestrator.yml'),
    configDir,
    persistence: persistenceBackend,
    resultBackend: resultBackend,
  });

  try {
    // Launch orchestrator (which launches worker nodes)
    const result = await orchestrator.execute();
    console.log('Orchestrator result:', result);

    // Simulate worker node processing independently
    console.log('\n=== Worker Node Processing ===');
    const workerNode = new FlatMachine({
      config: join(configDir, 'worker_node.yml'),
      configDir,
      persistence: persistenceBackend,
      resultBackend: resultBackend,
    });

    const workerResult = await workerNode.execute({
      tasks: [
        { task: "summarize", data: "This is text to summarize." },
        { task: "analyze", data: "Data elements to analyze." }
      ]
    });
    console.log('Worker node result:', JSON.stringify(workerResult, null, 2));

    // Demonstrate checkpoint/resume
    console.log('\n=== Checkpoint/Resume Demo ===');
    if (workerNode.executionId) {
      console.log(`Execution ID: ${workerNode.executionId}`);
      console.log('Could resume from checkpoint using this ID');
    }

  } catch (error) {
    console.error('Error:', error);
  }
}

main();
