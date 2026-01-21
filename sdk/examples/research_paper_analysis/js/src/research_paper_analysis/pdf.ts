import { mkdir, readFile, writeFile, access } from 'fs/promises';
import { createRequire } from 'module';
import { dirname, join, sep } from 'path';
import { pathToFileURL } from 'url';
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist/legacy/build/pdf.mjs';
import type { TextItem, TextMarkedContent } from 'pdfjs-dist/types/src/display/api.js';

const PAPER_PDF_URL = 'https://arxiv.org/pdf/1706.03762.pdf';
const require = createRequire(import.meta.url);
const workerPath = require.resolve('pdfjs-dist/legacy/build/pdf.worker.mjs');
const packagePath = require.resolve('pdfjs-dist/package.json');
const standardFontPath = join(dirname(packagePath), 'standard_fonts');
const standardFontDataUrl = standardFontPath.endsWith(sep) ? standardFontPath : `${standardFontPath}${sep}`;

GlobalWorkerOptions.workerSrc = pathToFileURL(workerPath).toString();

function isTextItem(item: TextItem | TextMarkedContent): item is TextItem {
  return 'str' in item;
}

export async function ensurePaperDownloaded(dataDir: string): Promise<string> {
  await mkdir(dataDir, { recursive: true });
  const pdfPath = join(dataDir, 'attention_is_all_you_need.pdf');

  try {
    await access(pdfPath);
    return pdfPath;
  } catch {
    // Continue to download
  }

  console.log(`Downloading paper from: ${PAPER_PDF_URL}`);
  const response = await fetch(PAPER_PDF_URL);
  if (!response.ok) {
    throw new Error(`Failed to download PDF: ${response.status} ${response.statusText}`);
  }
  const buffer = Buffer.from(await response.arrayBuffer());
  await writeFile(pdfPath, buffer);
  console.log(`Downloaded to: ${pdfPath}`);

  return pdfPath;
}

export async function extractTextFromPdf(pdfPath: string, dataDir: string): Promise<string> {
  const textPath = join(dataDir, 'attention_is_all_you_need.txt');

  try {
    const cached = await readFile(textPath, 'utf8');
    if (cached.trim().length) {
      return cached;
    }
  } catch {
    // Ignore cache miss
  }

  console.log('Extracting text from PDF...');
  const pdfData = new Uint8Array(await readFile(pdfPath));
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
  await writeFile(textPath, text);
  console.log(`Extracted ${text.length} chars to ${textPath}`);

  return text;
}
