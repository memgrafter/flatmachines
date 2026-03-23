#!/usr/bin/env node
import { FlatMachine } from '@memgrafter/flatmachines';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { mkdirSync, writeFileSync } from 'fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const rootDir = join(__dirname, '..', '..', '..');
const configDir = join(rootDir, 'config');

type Args = {
  genre: string;
  premise: string;
  numChapters: number;
  resumeId?: string;
};

function parseArgs(argv: string[]): Args {
  const args: Args = {
    genre: 'science fiction',
    premise: 'A librarian discovers books can transport readers into their stories',
    numChapters: 2,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--genre' && argv[i + 1]) {
      args.genre = argv[i + 1];
      i += 1;
    } else if (arg === '--premise' && argv[i + 1]) {
      args.premise = argv[i + 1];
      i += 1;
    } else if (arg === '--num-chapters' && argv[i + 1]) {
      const parsed = Number(argv[i + 1]);
      if (!Number.isNaN(parsed) && parsed > 0) {
        args.numChapters = parsed;
      }
      i += 1;
    } else if (arg === '--resume' && argv[i + 1]) {
      args.resumeId = argv[i + 1];
      i += 1;
    }
  }

  return args;
}

function flattenChapters(data: unknown): string[] {
  if (typeof data === 'string') {
    try {
      const parsed = JSON.parse(data);
      return flattenChapters(parsed);
    } catch {
      return [data];
    }
  }
  if (Array.isArray(data)) {
    const flattened: string[] = [];
    for (const item of data) {
      flattened.push(...flattenChapters(item));
    }
    return flattened;
  }
  if (data === null || data === undefined) {
    return [];
  }
  return [String(data)];
}

function sanitizeTitle(title: string): string {
  const cleaned = title.replace(/[^a-zA-Z0-9 _-]/g, '').trim();
  const safe = cleaned.replace(/\s+/g, '_');
  return safe.length ? safe : 'Untitled';
}

async function main() {
  const { genre, premise, numChapters, resumeId } = parseArgs(process.argv.slice(2));

  const machine = new FlatMachine({
    config: join(configDir, 'machine.yml'),
    configDir,
  });

  try {
    console.log('='.repeat(60));
    console.log('Multi-Chapter Story Writer (Machine Topology + Checkpoint)');
    console.log('='.repeat(60));
    console.log(`Machine: ${machine.config.data.name}`);
    console.log(`Genre: ${genre}`);
    console.log(`Premise: ${premise}`);
    console.log(`Chapters: ${numChapters}`);
    if (resumeId) {
      console.log(`Resuming from: ${resumeId}`);
    }
    console.log('-'.repeat(60));

    const result = resumeId
      ? await machine.resume(resumeId)
      : await machine.execute({
          genre,
          premise,
          num_chapters: numChapters,
        });

    console.log('='.repeat(60));
    console.log('STORY COMPLETE');
    console.log('='.repeat(60));

    const title = String(result?.title ?? 'Untitled');
    const chaptersCompleted = Number(result?.chapters_completed ?? 0);
    console.log(`Title: ${title}`);
    console.log(`Chapters Written: ${Number.isFinite(chaptersCompleted) ? chaptersCompleted : 0}`);

    const chapters = flattenChapters(result?.chapters ?? []);

    for (const [index, chapter] of chapters.slice(0, 3).entries()) {
      const preview = chapter.length > 300 ? `${chapter.slice(0, 300)}...` : chapter;
      console.log(`\n--- Chapter ${index + 1} Preview ---`);
      console.log(preview);
    }

    console.log('\n--- Statistics ---');
    console.log(`Execution ID: ${machine.executionId}`);
    const totalApiCalls = (machine as any).total_api_calls ?? (machine as any).totalApiCalls;
    const totalCost = (machine as any).total_cost ?? (machine as any).totalCost;
    if (typeof totalApiCalls === 'number') {
      console.log(`Total API calls: ${totalApiCalls}`);
    } else {
      console.log('Total API calls: n/a');
    }
    if (typeof totalCost === 'number') {
      console.log(`Estimated cost: $${totalCost.toFixed(4)}`);
    } else {
      console.log('Estimated cost: n/a');
    }

    const outputDir = join(rootDir, 'output');
    mkdirSync(outputDir, { recursive: true });
    const safeTitle = sanitizeTitle(title);
    const outputFile = join(outputDir, `${safeTitle}.md`);

    let contents = `# ${title}\n\n`;
    contents += `*Genre: ${genre}*\n\n`;
    contents += `*Premise: ${premise}*\n\n`;
    contents += '---\n\n';

    chapters.forEach((chapter, index) => {
      let chapterText = String(chapter);
      chapterText = chapterText.replace(/\\n/g, '\n');
      chapterText = chapterText.trim().replace(/^[\[\]'\"]+|[\[\]'\"]+$/g, '');
      contents += `## Chapter ${index + 1}\n\n`;
      contents += `${chapterText}\n\n`;
    });

    writeFileSync(outputFile, contents, 'utf-8');
    console.log(`\n📖 Story saved to: ${outputFile}`);
  } catch (error) {
    console.error('Error:', error);
  }
}

main();
