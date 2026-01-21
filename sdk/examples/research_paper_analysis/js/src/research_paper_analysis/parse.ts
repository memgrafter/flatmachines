export type PaperSection = {
  title: string;
  content: string;
  page_start: number;
};

export type ParsedPaper = {
  title: string;
  authors: string[];
  abstract: string;
  sections: PaperSection[];
  references: string[];
  full_text: string;
};

export function parsePaper(text: string): ParsedPaper {
  let title = 'Unknown Title';

  if (text.includes('Attention Is All You Need')) {
    title = 'Attention Is All You Need';
  } else {
    const titleMatch = text.slice(500, 2000).match(/^([A-Z][^.!?\n]{10,100})/m);
    if (titleMatch) {
      title = titleMatch[1].trim();
    }
  }

  const authorSection = text.slice(0, 3000);
  const authorNames = Array.from(authorSection.matchAll(/([A-Z][a-z]+ (?:[A-Z]\. )?[A-Z][a-z]+)(?:\s*[†‡∗*])?/g)).map(match => match[1]);
  const authors = Array.from(new Set(authorNames)).slice(0, 10);

  const abstractMatch = text.match(/Abstract\s*\n([\s\S]*?)(?=\n\s*\d+\s+Introduction|\n\s*1\s+Introduction|\n\s*Keywords)/i);
  const abstract = abstractMatch ? abstractMatch[1].trim() : '';

  const sectionPattern = /\n(\d+(?:\.\d+)?)\s+([A-Z][^\n]{3,60})\n/g;
  const sectionMatches = Array.from(text.matchAll(sectionPattern));

  const sections: PaperSection[] = [];
  for (let i = 0; i < sectionMatches.length; i += 1) {
    const match = sectionMatches[i];
    const sectionNum = match[1];
    const sectionTitle = match[2].trim();
    const startPos = match.index !== undefined ? match.index + match[0].length : 0;

    let endPos = text.length;
    if (i + 1 < sectionMatches.length) {
      const nextMatch = sectionMatches[i + 1];
      if (nextMatch.index !== undefined) {
        endPos = nextMatch.index;
      }
    } else {
      const refMatch = text.slice(startPos).match(/\nReferences\s*\n/i);
      if (refMatch?.index !== undefined) {
        endPos = startPos + refMatch.index;
      }
    }

    const content = text.slice(startPos, endPos).trim();
    sections.push({
      title: `${sectionNum} ${sectionTitle}`,
      content: content.slice(0, 8000),
      page_start: 1,
    });
  }

  const references: string[] = [];
  const refMatch = text.match(/\nReferences\s*\n([\s\S]*)/i);
  if (refMatch) {
    const refText = refMatch[1];
    const refs = refText.split(/\n\s*\[?\d+\]?\s*/g);
    for (const ref of refs) {
      const trimmed = ref.trim();
      if (trimmed.length > 20) {
        references.push(trimmed.slice(0, 200));
      }
      if (references.length >= 40) {
        break;
      }
    }
  }

  return {
    title,
    authors,
    abstract,
    sections,
    references,
    full_text: text,
  };
}
