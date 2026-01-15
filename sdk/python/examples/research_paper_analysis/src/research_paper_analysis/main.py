"""
Research Paper Analysis Demo for FlatAgents (Machine Topology + Checkpoint/Resume).

Demonstrates:
- Machine Peering: Main machine launches and coordinates peer machines
- Checkpoint/Resume: Survives crashes, resumes from last state
- Multi-stage Pipeline: Extract → Analyze Sections → Synthesize

This is a PRODUCTION-QUALITY demo that handles full papers (40KB+).
Uses programmatic extraction for parsing, LLM only for analysis.

Usage:
    python -m research_paper_analysis.main
    ./run.sh
"""

import re
import asyncio
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional

import httpx
from pypdf import PdfReader

from flatagents import FlatMachine, LoggingHooks, setup_logging, get_logger

setup_logging(level='INFO')
logger = get_logger(__name__)

# Paper PDF URL and local paths
PAPER_PDF_URL = "https://arxiv.org/pdf/1706.03762.pdf"
DATA_DIR = Path(__file__).parent.parent.parent / 'data'
PAPER_PDF_PATH = DATA_DIR / 'attention_is_all_you_need.pdf'
PAPER_TXT_PATH = DATA_DIR / 'attention_is_all_you_need.txt'


@dataclass
class PaperSection:
    """A section of a research paper."""
    title: str
    content: str
    page_start: int


@dataclass  
class ParsedPaper:
    """Programmatically parsed research paper."""
    title: str
    authors: List[str]
    abstract: str
    sections: List[PaperSection]
    references: List[str]
    full_text: str


def ensure_paper_downloaded() -> Path:
    """Download PDF if needed. Returns path to PDF."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    if not PAPER_PDF_PATH.exists():
        logger.info(f"Downloading paper from: {PAPER_PDF_URL}")
        response = httpx.get(PAPER_PDF_URL, follow_redirects=True, timeout=60.0)
        response.raise_for_status()
        PAPER_PDF_PATH.write_bytes(response.content)
        logger.info(f"Downloaded to: {PAPER_PDF_PATH}")
    
    return PAPER_PDF_PATH


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract text from PDF using pypdf."""
    if PAPER_TXT_PATH.exists():
        return PAPER_TXT_PATH.read_text()
    
    logger.info("Extracting text from PDF...")
    reader = PdfReader(pdf_path)
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        pages.append(f"[PAGE {i+1}]\n{text}")
    
    full_text = "\n\n".join(pages)
    PAPER_TXT_PATH.write_text(full_text)
    logger.info(f"Extracted {len(full_text)} chars to {PAPER_TXT_PATH}")
    return full_text


def parse_paper_programmatically(text: str, pdf_path: Path = None) -> ParsedPaper:
    """
    Parse paper using regex and string operations - NO LLM.
    This is fast, deterministic, and handles large documents.
    
    Title extraction priority:
    1. PDF metadata (if available and valid)
    2. Known paper title check
    3. Regex fallback
    """
    title = "Unknown Title"
    
    # Try PDF metadata first (see RSCH_TITLE_FIX.md)
    if pdf_path and pdf_path.exists():
        try:
            reader = PdfReader(pdf_path)
            if reader.metadata and reader.metadata.title:
                candidate = reader.metadata.title.strip()
                # Validate: must be reasonable length and not generic
                if 5 < len(candidate) < 200 and "arXiv" not in candidate:
                    title = candidate
        except Exception:
            pass
    
    # Fallback: check for known paper title
    if title == "Unknown Title" and "Attention Is All You Need" in text:
        title = "Attention Is All You Need"
    
    # Fallback: regex extraction
    if title == "Unknown Title":
        title_match = re.search(r'^([A-Z][^.!?\n]{10,100})', text[500:2000], re.MULTILINE)
        title = title_match.group(1).strip() if title_match else "Unknown Title"
    
    # Extract authors (look for email patterns nearby)
    author_section = text[:3000]  # Authors usually in first few pages
    emails = re.findall(r'[\w.+-]+@[\w.-]+', author_section)
    # Extract names near emails
    author_names = re.findall(r'([A-Z][a-z]+ (?:[A-Z]\. )?[A-Z][a-z]+)(?:\s*[†‡∗*])?', author_section)
    authors = list(set(author_names[:10]))  # Dedupe, limit
    
    # Extract abstract
    abstract_match = re.search(
        r'Abstract\s*\n(.*?)(?=\n\s*\d+\s+Introduction|\n\s*1\s+Introduction|\n\s*Keywords)',
        text, re.DOTALL | re.IGNORECASE
    )
    abstract = abstract_match.group(1).strip() if abstract_match else ""
    
    # Extract sections by numbered headers
    section_pattern = r'\n(\d+(?:\.\d+)?)\s+([A-Z][^\n]{3,60})\n'
    section_matches = list(re.finditer(section_pattern, text))
    
    sections = []
    for i, match in enumerate(section_matches):
        section_num = match.group(1)
        section_title = match.group(2).strip()
        start_pos = match.end()
        
        # Find end of section (next section or end of text)
        if i + 1 < len(section_matches):
            end_pos = section_matches[i + 1].start()
        else:
            # Last section ends at References or end
            ref_match = re.search(r'\nReferences\s*\n', text[start_pos:])
            end_pos = start_pos + ref_match.start() if ref_match else len(text)
        
        content = text[start_pos:end_pos].strip()
        
        # Estimate page number
        page_markers = re.findall(r'\[PAGE (\d+)\]', text[:start_pos])
        page_start = int(page_markers[-1]) if page_markers else 1
        
        sections.append(PaperSection(
            title=f"{section_num} {section_title}",
            content=content[:8000],  # Limit per-section for LLM context
            page_start=page_start
        ))
    
    # Extract references
    ref_match = re.search(r'\nReferences\s*\n(.*)', text, re.DOTALL | re.IGNORECASE)
    references = []
    if ref_match:
        ref_text = ref_match.group(1)
        # Split by numbered citations [1], [2], etc.
        refs = re.split(r'\n\s*\[?\d+\]?\s*', ref_text)
        references = [r.strip()[:200] for r in refs if len(r.strip()) > 20][:40]
    
    return ParsedPaper(
        title=title,
        authors=authors,
        abstract=abstract,
        sections=sections,
        references=references,
        full_text=text
    )


async def run(resume_id: str = None):
    """
    Run the research paper analysis pipeline.

    Args:
        resume_id: Optional execution ID to resume from checkpoint
    """
    # Step 1: Ensure paper is downloaded
    pdf_path = ensure_paper_downloaded()
    
    # Step 2: Extract text (programmatic, fast)
    full_text = extract_text_from_pdf(pdf_path)
    
    # Step 3: Parse paper structure (programmatic, fast)
    logger.info("Parsing paper structure...")
    paper = parse_paper_programmatically(full_text, pdf_path=pdf_path)
    
    logger.info("=" * 60)
    logger.info("Research Paper Analysis (Machine Topology + Checkpoint)")
    logger.info("=" * 60)
    logger.info(f"Title: {paper.title}")
    logger.info(f"Authors: {', '.join(paper.authors[:5])}")
    logger.info(f"Abstract: {len(paper.abstract)} chars")
    logger.info(f"Sections: {len(paper.sections)}")
    logger.info(f"References: {len(paper.references)}")
    logger.info("-" * 60)

    # Step 4: Run FlatMachine for LLM-based analysis
    config_path = Path(__file__).parent.parent.parent / 'config' / 'machine.yml'
    machine = FlatMachine(
        config_file=str(config_path),
        hooks=LoggingHooks()
    )

    logger.info(f"Machine: {machine.machine_name}")
    logger.info(f"States: {list(machine.states.keys())}")
    if resume_id:
        logger.info(f"Resuming from: {resume_id}")
    logger.info("-" * 60)

    # Prepare structured input for the machine
    # The machine will use this pre-parsed data, not raw text
    sections_summary = "\n".join([
        f"- {s.title}: {len(s.content)} chars"
        for s in paper.sections
    ])
    
    # Pre-format section contents as text (avoid Jinja2 iteration issues)
    section_text = "\n\n".join([
        f"=== {s.title} ===\n{s.content[:3000]}"
        for s in paper.sections[:6]  # First 6 main sections
    ])
    
    result = await machine.execute(
        input={
            "title": paper.title,
            "authors": ", ".join(paper.authors),
            "abstract": paper.abstract,
            "sections": sections_summary,
            "section_text": section_text,  # Pre-formatted text
            "reference_count": len(paper.references),
            "references_sample": paper.references[:10],
        },
    )

    logger.info("=" * 60)
    logger.info("ANALYSIS COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Title: {result.get('title', paper.title)}")
    logger.info(f"Quality Score: {result.get('quality_score', 'N/A')}/10")
    logger.info(f"Citations Found: {result.get('citation_count', len(paper.references))}")
    summary = result.get('summary', 'N/A')
    logger.info(f"Summary Preview: {summary[:200]}..." if len(str(summary)) > 200 else f"Summary: {summary}")

    # Save formatted report to data folder
    formatted_report = result.get('formatted_report', '')
    if formatted_report:
        report_path = DATA_DIR / 'analysis_report.md'
        report_path.write_text(formatted_report)
        logger.info(f"\n📄 Report saved to: {report_path}")
    
    logger.info("--- Statistics ---")
    logger.info(f"Execution ID: {machine.execution_id}")
    logger.info(f"Total API calls: {machine.total_api_calls}")
    logger.info(f"Estimated cost: ${machine.total_cost:.4f}")

    return result


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
