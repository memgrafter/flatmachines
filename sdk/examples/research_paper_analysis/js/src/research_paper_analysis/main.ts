#!/usr/bin/env node
import { FlatMachine } from 'flatagents';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { mkdirSync, writeFileSync } from 'fs';
import { ensurePaperDownloaded, extractTextFromPdf } from './pdf.js';
import { parsePaper } from './parse.js';

async function main() {
  const __filename = fileURLToPath(import.meta.url);
  const __dirname = dirname(__filename);
  const rootDir = join(__dirname, '..', '..', '..');
  const configDir = join(rootDir, 'config');
  const dataDir = join(rootDir, 'data');

  mkdirSync(dataDir, { recursive: true });

  const pdfPath = await ensurePaperDownloaded(dataDir);
  const fullText = await extractTextFromPdf(pdfPath, dataDir);

  console.log('Parsing paper structure...');
  const paper = parsePaper(fullText);

  console.log('='.repeat(60));
  console.log('Research Paper Analysis (Machine Topology + Checkpoint)');
  console.log('='.repeat(60));
  console.log(`Title: ${paper.title}`);
  console.log(`Authors: ${paper.authors.slice(0, 5).join(', ')}`);
  console.log(`Abstract: ${paper.abstract.length} chars`);
  console.log(`Sections: ${paper.sections.length}`);
  console.log(`References: ${paper.references.length}`);
  console.log('-'.repeat(60));

  const machine = new FlatMachine({
    config: join(configDir, 'machine.yml'),
    configDir,
  });

  const sectionsSummary = paper.sections.map(section => `- ${section.title}: ${section.content.length} chars`).join('\n');
  const sectionText = paper.sections.slice(0, 6)
    .map(section => `=== ${section.title} ===\n${section.content.slice(0, 3000)}`)
    .join('\n\n');

  const result = await machine.execute({
    title: paper.title,
    authors: paper.authors.join(', '),
    abstract: paper.abstract,
    sections: sectionsSummary,
    section_text: sectionText,
    reference_count: paper.references.length,
    references_sample: paper.references.slice(0, 10),
  });

  console.log('='.repeat(60));
  console.log('ANALYSIS COMPLETE');
  console.log('='.repeat(60));
  console.log(`Title: ${result?.title ?? paper.title}`);
  console.log(`Quality Score: ${result?.quality_score ?? 'N/A'}/10`);
  console.log(`Citations Found: ${result?.citation_count ?? paper.references.length}`);
  const summary = result?.summary ?? 'N/A';
  if (String(summary).length > 200) {
    console.log(`Summary Preview: ${String(summary).slice(0, 200)}...`);
  } else {
    console.log(`Summary: ${summary}`);
  }

  const formattedReport = result?.formatted_report ?? '';
  if (formattedReport) {
    const reportPath = join(dataDir, 'analysis_report.md');
    writeFileSync(reportPath, formattedReport, 'utf8');
    console.log(`\n📄 Report saved to: ${reportPath}`);
  }

  console.log('--- Statistics ---');
  console.log(`Execution ID: ${machine.executionId}`);
  const totalApiCalls = (machine as any).total_api_calls ?? (machine as any).totalApiCalls;
  const totalCost = (machine as any).total_cost ?? (machine as any).totalCost;
  console.log(`Total API calls: ${typeof totalApiCalls === 'number' ? totalApiCalls : 'n/a'}`);
  console.log(`Estimated cost: ${typeof totalCost === 'number' ? `$${totalCost.toFixed(4)}` : 'n/a'}`);
}

main().catch(error => {
  console.error('Error:', error);
  process.exit(1);
});
