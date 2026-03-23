#!/usr/bin/env node
import { FlatAgent, FlatMachine } from '@memgrafter/flatmachines';
import { fileURLToPath, pathToFileURL } from 'url';
import { dirname, join, sep } from 'path';
import { mkdirSync, readFileSync, writeFileSync, existsSync } from 'fs';
import { createRequire } from 'module';
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist/legacy/build/pdf.mjs';
import type { TextItem, TextMarkedContent } from 'pdfjs-dist/types/src/display/api.js';

const require = createRequire(import.meta.url);
const workerPath = require.resolve('pdfjs-dist/legacy/build/pdf.worker.mjs');
const packagePath = require.resolve('pdfjs-dist/package.json');
const standardFontPath = join(dirname(packagePath), 'standard_fonts');
const standardFontDataUrl = standardFontPath.endsWith(sep) ? standardFontPath : `${standardFontPath}${sep}`;

GlobalWorkerOptions.workerSrc = pathToFileURL(workerPath).toString();

const PAPER_REGISTRY: Record<string, { title: string; url: string; filename: string }> = {
  gepa: {
    title: 'GEPA: Reflective Prompt Evolution',
    url: 'https://arxiv.org/pdf/2507.19457.pdf',
    filename: 'gepa_prompt_evolution.pdf',
  },
  mipro: {
    title: 'MIPRO: Multi-prompt Instruction Optimization',
    url: 'https://arxiv.org/pdf/2406.11695.pdf',
    filename: 'mipro_dspy.pdf',
  },
  textgrad: {
    title: 'TextGrad: Automatic Differentiation via Text',
    url: 'https://arxiv.org/pdf/2406.07496.pdf',
    filename: 'textgrad.pdf',
  },
};

type ParsedPaper = {
  title: string;
  authors: string;
  abstract: string;
  sections: string;
  section_text: string;
  reference_count: number;
  references_sample: string[];
};

const SECTION_KEYWORDS = [
  'INTRODUCTION',
  'BACKGROUND',
  'RELATED',
  'PRELIMINARIES',
  'PROBLEM',
  'METHOD',
  'METHODOLOGY',
  'APPROACH',
  'EXPERIMENT',
  'EVALUATION',
  'RESULT',
  'DISCUSSION',
  'CONCLUSION',
  'LIMITATIONS',
  'FUTURE',
  'REFERENCES',
  'APPENDIX',
  'DATA',
  'MODEL',
  'ALGORITHM',
  'ARCHITECTURE',
  'SETUP',
  'IMPLEMENTATION',
  'ANALYSIS',
  'TRAINING',
  'OBJECTIVE',
];

function isTextItem(item: TextItem | TextMarkedContent): item is TextItem {
  return 'str' in item;
}

function normalizePdfText(raw: string): string {
  let text = raw.replace(/\r/g, '\n');
  text = text.replace(/\b([A-Z])\s+([A-Z]{2,})\b/g, '$1$2');
  text = text.replace(/\b(?:[A-Z]\s+){2,}[A-Z]\b/g, match => match.replace(/\s+/g, ''));
  text = text.replace(/-\s+\n/g, '');
  text = text.replace(/\s+/g, ' ');
  return text.trim();
}

function cleanSectionTitle(rawTitle: string): string {
  const tokens = rawTitle.trim().split(/\s+/);
  const cleaned: string[] = [];
  for (const token of tokens) {
    if (/^\d+(\.\d+)?$/.test(token)) {
      break;
    }
    cleaned.push(token);
  }
  return cleaned.join(' ').replace(/[:\-]+$/g, '').trim();
}

function isLikelySectionTitle(title: string, sectionNumber: string): boolean {
  if (!title || title.length < 4) return false;
  if (title.includes('ABSTRACT')) return false;
  if (title.startsWith('FIGURE') || title.startsWith('TABLE') || title.startsWith('ALGORITHM')) return false;
  const numberValue = Number.parseFloat(sectionNumber);
  if (!Number.isFinite(numberValue) || numberValue <= 0 || numberValue > 50) return false;
  const digitCount = (title.match(/\d/g) ?? []).length;
  if (digitCount > Math.max(2, Math.floor(title.length * 0.2))) return false;
  const tokens = title.split(/\s+/);
  const shortTokens = tokens.filter(token => token.length <= 1).length;
  if (shortTokens / tokens.length > 0.34) return false;
  return SECTION_KEYWORDS.some(keyword => title.includes(keyword));
}

function extractAbstract(normalized: string): string {
  const upper = normalized.toUpperCase();
  const startIndex = upper.indexOf('ABSTRACT');
  if (startIndex === -1) return '';
  let start = startIndex + 'ABSTRACT'.length;
  if (normalized[start] === ':' || normalized[start] === '-') start += 1;
  const endMarkers = ['INTRODUCTION', '1 INTRODUCTION', 'I INTRODUCTION', 'KEYWORDS', 'INDEX TERMS'];
  let end = normalized.length;
  for (const marker of endMarkers) {
    const idx = upper.indexOf(marker, start);
    if (idx !== -1 && idx < end) {
      end = idx;
    }
  }
  return normalized.slice(start, end).trim().slice(0, 2000);
}

type Section = {
  number: string;
  title: string;
  content: string;
};

function extractSections(normalized: string): Section[] {
  const sections: Array<{ number: string; title: string; index: number; end: number }> = [];
  const pattern = /\b(\d+(?:\.\d+)?)\s+([A-Z][A-Z0-9][A-Z0-9\s\-:]{2,120})/g;
  for (const match of normalized.matchAll(pattern)) {
    if (match.index === undefined) continue;
    const number = match[1];
    const rawTitle = match[2];
    const title = cleanSectionTitle(rawTitle);
    if (!isLikelySectionTitle(title, number)) {
      continue;
    }
    sections.push({
      number,
      title,
      index: match.index,
      end: match.index + match[0].length,
    });
  }

  const deduped: Array<{ number: string; title: string; index: number; end: number }> = [];
  for (const section of sections) {
    const last = deduped[deduped.length - 1];
    if (last && Math.abs(last.index - section.index) < 10 && last.title === section.title) {
      continue;
    }
    deduped.push(section);
  }

  deduped.sort((a, b) => a.index - b.index);

  const results: Section[] = [];
  for (let i = 0; i < deduped.length; i += 1) {
    const current = deduped[i];
    const next = deduped[i + 1];
    const end = next ? next.index : normalized.length;
    const content = normalized.slice(current.end, end).trim();
    results.push({ number: current.number, title: current.title, content });
  }
  return results;
}

function extractSection(text: string, header: string): string {
  if (!text) return '';
  const upper = text.toUpperCase();
  const startIndex = upper.indexOf(header.toUpperCase());
  if (startIndex === -1) return '';
  let start = startIndex + header.length;
  if (text[start] === ':') start += 1;

  const markers = [
    '\nKEY FINDINGS:',
    '\nMETHODOLOGY:',
    '\nCONTRIBUTIONS:',
    '\nTECHNICAL DETAILS:',
    '\nRESULTS:',
    '\nCOMMON THEMES:',
    '\nKEY DIFFERENCES:',
    '\nRESEARCH GAPS:',
    '\nOPPORTUNITIES:',
    '\nQUALITY SCORE:',
    '\nCRITIQUE:',
  ];

  let end = text.length;
  for (const marker of markers) {
    const pos = upper.indexOf(marker.toUpperCase(), start);
    if (pos !== -1 && pos < end) {
      end = pos;
    }
  }

  return text.slice(start, end).trim();
}

function extractScore(text: string): number {
  if (!text) return 0;
  const idx = text.toUpperCase().indexOf('QUALITY SCORE');
  if (idx === -1) return 0;
  const snippet = text.slice(idx, idx + 30);
  for (const char of snippet) {
    if (/[0-9]/.test(char)) {
      const value = Number.parseInt(char, 10);
      return Math.min(10, Math.max(1, value));
    }
  }
  return 0;
}

async function ensurePaperDownloaded(paperId: string, papersDir: string): Promise<string> {
  const paperInfo = PAPER_REGISTRY[paperId];
  const pdfPath = join(papersDir, paperInfo.filename);
  if (existsSync(pdfPath)) {
    return pdfPath;
  }

  console.log(`Downloading ${paperInfo.title} from ${paperInfo.url}`);
  try {
    const response = await fetch(paperInfo.url);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const buffer = Buffer.from(await response.arrayBuffer());
    writeFileSync(pdfPath, buffer);
    console.log(`Downloaded to: ${pdfPath}`);
    return pdfPath;
  } catch (error) {
    console.warn(`Could not download ${paperId}: ${error}`);
    writeFileSync(pdfPath, `[Placeholder for ${paperInfo.title}]`);
    return pdfPath;
  }
}

async function extractTextFromPdf(pdfPath: string): Promise<string> {
  const txtPath = pdfPath.replace(/\.pdf$/i, '.txt');
  if (existsSync(txtPath)) {
    return readFileSync(txtPath, 'utf8');
  }

  try {
    const pdfData = new Uint8Array(readFileSync(pdfPath));
    const loadingTask = getDocument({ data: pdfData, standardFontDataUrl });
    const pdf = await loadingTask.promise;

    let text = '';
    for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
      const page = await pdf.getPage(pageNumber);
      const content = await page.getTextContent();
      const pageText = content.items
        .filter(isTextItem)
        .map((item) => item.str)
        .join(' ')
        .trim();

      if (pageText.length) {
        text += `${pageText}\n\n`;
      }
    }

    text = text.trimEnd();
    writeFileSync(txtPath, text);
    console.log(`Extracted ${text.length} chars from ${pdfPath}`);
    return text;
  } catch (error) {
    console.warn(`Could not extract text from ${pdfPath}: ${error}`);
    return `[Could not extract text from ${pdfPath}]`;
  }
}

function parsePaperProgrammatically(text: string, paperInfo: { title: string }): ParsedPaper {
  const normalized = normalizePdfText(text);
  const upper = normalized.toUpperCase();
  const title = paperInfo.title ?? 'Unknown Title';

  const authorSection = normalized.slice(0, 3000);
  const authorMatches = Array.from(authorSection.matchAll(/([A-Z][a-z]+ (?:[A-Z]\. )?[A-Z][a-z]+)(?:\s*[†‡∗*])?/g));
  const authors = Array.from(new Set(authorMatches.map(match => match[1]))).slice(0, 8).join(', ');

  const abstract = extractAbstract(normalized);

  let sections = extractSections(normalized);
  if (sections.length === 0) {
    const introIndex = upper.indexOf('INTRODUCTION');
    const fallbackContent = normalized.slice(Math.max(0, introIndex));
    sections = [{
      number: '1',
      title: introIndex === -1 ? 'BODY' : 'INTRODUCTION',
      content: fallbackContent,
    }];
  }

  const sectionsSummary = sections
    .slice(0, 15)
    .map(section => `- ${section.number} ${section.title}`)
    .join('\n');

  const sectionTextParts = sections.slice(0, 6).map(section => {
    const content = section.content.trim().slice(0, 2500);
    return `=== ${section.number} ${section.title} ===\n${content}`;
  });

  const sectionText = sectionTextParts.join('\n\n');

  const references: string[] = [];
  const refIndex = upper.indexOf('REFERENCES');
  if (refIndex !== -1) {
    const refText = normalized.slice(refIndex + 'REFERENCES'.length);
    const refs = refText.split(/\s+\[?\d+\]?\s+/g);
    for (const ref of refs) {
      const trimmed = ref.trim();
      if (trimmed.length > 20) {
        references.push(trimmed.slice(0, 200));
      }
      if (references.length >= 30) break;
    }
  }

  return {
    title,
    authors,
    abstract,
    sections: sectionsSummary,
    section_text: sectionText,
    reference_count: references.length,
    references_sample: references.slice(0, 10),
  };
}

async function analyzeSinglePaper(paperId: string, baseDir: string): Promise<Record<string, any>> {
  const paperInfo = PAPER_REGISTRY[paperId];
  const papersDir = join(baseDir, 'data', 'papers');
  mkdirSync(papersDir, { recursive: true });

  const pdfPath = await ensurePaperDownloaded(paperId, papersDir);
  const text = await extractTextFromPdf(pdfPath);
  const paper = parsePaperProgrammatically(text, paperInfo);

  console.log(`Analyzing: ${paper.title}`);
  console.log(`  Abstract: ${paper.abstract.length} chars`);
  console.log(`  Sections: ${paper.sections.split('\n').length} found`);

  const analyzerConfig = join(baseDir, 'paper_analyzer', 'config', 'machine.yml');
  const analyzer = new FlatMachine({
    config: analyzerConfig,
    configDir: join(baseDir, 'paper_analyzer', 'config'),
  });

  const analysis = await analyzer.execute({
    title: paper.title,
    authors: paper.authors,
    abstract: paper.abstract,
    sections: paper.sections,
    section_text: paper.section_text,
    reference_count: paper.reference_count,
    references_sample: paper.references_sample,
  });

  return {
    id: paperId,
    title: paper.title,
    analysis,
  };
}

async function synthesizePapers(paperIds: string[], researchQuestion: string, baseDir: string) {
  console.log('='.repeat(60));
  console.log('Multi-Paper Research Synthesizer');
  console.log('='.repeat(60));
  console.log(`Research Question: ${researchQuestion}`);
  console.log(`Papers to analyze: ${paperIds.join(', ')}`);
  console.log('-'.repeat(60));

  const paperAnalyses: Record<string, any>[] = [];
  for (const paperId of paperIds) {
    if (PAPER_REGISTRY[paperId]) {
      const analysis = await analyzeSinglePaper(paperId, baseDir);
      paperAnalyses.push(analysis);
    } else {
      console.warn(`Unknown paper ID: ${paperId}`);
    }
  }

  console.log(`\nAnalyzed ${paperAnalyses.length} papers`);
  console.log('-'.repeat(60));

  const analysesText = paperAnalyses.map(analysis => {
    const keyFindings = analysis.analysis?.key_findings ?? 'N/A';
    const summary = analysis.analysis?.summary ?? 'N/A';
    return `### ${analysis.title}\nKey Findings: ${keyFindings}\nSummary: ${String(summary).slice(0, 500)}`;
  }).join('\n\n');

  const configDir = join(baseDir, 'config');
  const comparator = new FlatAgent({ config: join(configDir, 'comparator.yml'), configDir });
  const compareResult = await comparator.call({
    research_question: researchQuestion,
    analyses: analysesText,
    paper_count: paperAnalyses.length,
  });

  const compareText = compareResult.content ?? '';
  const commonThemes = extractSection(compareText, 'COMMON THEMES');
  const keyDifferences = extractSection(compareText, 'KEY DIFFERENCES');

  const gapFinder = new FlatAgent({ config: join(configDir, 'gap_finder.yml'), configDir });
  const gapResult = await gapFinder.call({
    research_question: researchQuestion,
    common_themes: commonThemes,
    key_differences: keyDifferences,
    analyses: analysesText,
  });

  const gapText = gapResult.content ?? '';
  const researchGaps = extractSection(gapText, 'RESEARCH GAPS');
  const opportunities = extractSection(gapText, 'OPPORTUNITIES');

  const synthesizer = new FlatAgent({ config: join(configDir, 'synthesizer.yml'), configDir });
  let synthResult = await synthesizer.call({
    research_question: researchQuestion,
    paper_count: paperAnalyses.length,
    common_themes: commonThemes,
    key_differences: keyDifferences,
    research_gaps: researchGaps,
    opportunities,
  });

  let synthesis = synthResult.content ?? '';
  const critic = new FlatAgent({ config: join(configDir, 'critic.yml'), configDir });
  let qualityScore = 0;
  let critique = '';

  for (let iteration = 0; iteration < 3; iteration += 1) {
    const critiqueResult = await critic.call({
      research_question: researchQuestion,
      synthesis,
      paper_count: paperAnalyses.length,
    });

    const critiqueText = critiqueResult.content ?? '';
    qualityScore = extractScore(critiqueText);
    critique = extractSection(critiqueText, 'CRITIQUE');

    console.log(`Iteration ${iteration + 1}: Quality score = ${qualityScore}/10`);

    if (qualityScore >= 8) {
      break;
    }

    synthResult = await synthesizer.call({
      research_question: researchQuestion,
      paper_count: paperAnalyses.length,
      common_themes: commonThemes,
      key_differences: keyDifferences,
      research_gaps: researchGaps,
      opportunities,
      previous_synthesis: synthesis,
      critique,
    });
    synthesis = synthResult.content ?? synthesis;
  }

  const formatter = new FlatAgent({ config: join(configDir, 'formatter.yml'), configDir });
  const reportDate = new Date().toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
  const formatResult = await formatter.call({
    research_question: researchQuestion,
    paper_count: paperAnalyses.length,
    report_date: reportDate,
    common_themes: commonThemes,
    key_differences: keyDifferences,
    research_gaps: researchGaps,
    opportunities,
    synthesis,
    quality_score: qualityScore,
  });

  const synthesisReport = formatResult.content ?? '';
  const reportPath = join(baseDir, 'data', 'synthesis_report.md');
  writeFileSync(reportPath, synthesisReport, 'utf8');
  console.log(`\n📄 Report saved to: ${reportPath}`);

  return {
    paper_count: paperAnalyses.length,
    common_themes: commonThemes,
    key_differences: keyDifferences,
    research_gaps: researchGaps,
    synthesis_report: synthesisReport,
    quality_score: qualityScore,
  };
}

async function main() {
  const __filename = fileURLToPath(import.meta.url);
  const __dirname = dirname(__filename);
  const baseDir = join(__dirname, '..', '..', '..');

  const paperIds = ['gepa', 'mipro', 'textgrad'];
  const researchQuestion = 'What are the most effective techniques for optimizing LLM prompts, and how do gradient-free methods like GEPA compare to gradient-based approaches?';

  await synthesizePapers(paperIds, researchQuestion, baseDir);
}

main().catch(error => {
  console.error('Error:', error);
  process.exit(1);
});
