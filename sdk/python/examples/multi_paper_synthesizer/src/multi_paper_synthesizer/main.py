"""
Multi-Paper Research Synthesizer for FlatAgents.

Meta-example demonstrating:
- Machine composition (paper_analyzer as reusable peer)
- Multi-document synthesis with comparison and gap analysis
- Self-judging improvement loop for synthesis quality

Usage:
    python -m multi_paper_synthesizer.main
    ./run.sh
"""

import re
import json
import asyncio
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Optional

import httpx
from pypdf import PdfReader

from flatagents import FlatMachine, LoggingHooks, setup_logging, get_logger

setup_logging(level='INFO')
logger = get_logger(__name__)

# Directories
BASE_DIR = Path(__file__).parent.parent.parent
CONFIG_DIR = BASE_DIR / 'config'
DATA_DIR = BASE_DIR / 'data'
PAPERS_DIR = DATA_DIR / 'papers'
PAPER_ANALYZER_DIR = BASE_DIR / 'paper_analyzer' / 'config'

# Paper registry - papers to analyze
PAPER_REGISTRY = {
    "gepa": {
        "title": "GEPA: Reflective Prompt Evolution",
        "url": "https://arxiv.org/pdf/2507.19457.pdf",
        "filename": "gepa_prompt_evolution.pdf",
    },
    "mipro": {
        "title": "MIPRO: Multi-prompt Instruction Optimization",
        "url": "https://arxiv.org/pdf/2406.11695.pdf",
        "filename": "mipro_dspy.pdf",
    },
    "textgrad": {
        "title": "TextGrad: Automatic Differentiation via Text",
        "url": "https://arxiv.org/pdf/2406.07496.pdf",
        "filename": "textgrad.pdf",
    },
}


@dataclass
class ParsedPaper:
    """Programmatically parsed research paper."""
    title: str
    authors: str
    abstract: str
    sections: str
    section_text: str
    reference_count: int
    references_sample: List[str]


def ensure_paper_downloaded(paper_id: str) -> Path:
    """Download paper PDF if needed. Returns path to PDF."""
    PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    
    paper_info = PAPER_REGISTRY[paper_id]
    pdf_path = PAPERS_DIR / paper_info["filename"]
    
    if not pdf_path.exists():
        logger.info(f"Downloading {paper_info['title']} from {paper_info['url']}")
        try:
            response = httpx.get(paper_info["url"], follow_redirects=True, timeout=60.0)
            response.raise_for_status()
            pdf_path.write_bytes(response.content)
            logger.info(f"Downloaded to: {pdf_path}")
        except Exception as e:
            logger.warning(f"Could not download {paper_id}: {e}")
            # Create placeholder
            pdf_path.write_text(f"[Placeholder for {paper_info['title']}]")
    
    return pdf_path


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract text from PDF using pypdf."""
    txt_path = pdf_path.with_suffix('.txt')
    
    if txt_path.exists():
        return txt_path.read_text()
    
    try:
        reader = PdfReader(pdf_path)
        pages = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            pages.append(f"[PAGE {i+1}]\n{text}")
        
        full_text = "\n\n".join(pages)
        txt_path.write_text(full_text)
        logger.info(f"Extracted {len(full_text)} chars from {pdf_path.name}")
        return full_text
    except Exception as e:
        logger.warning(f"Could not extract text from {pdf_path}: {e}")
        return f"[Could not extract text from {pdf_path.name}]"


def parse_paper_programmatically(text: str, paper_info: dict, pdf_path: Path = None) -> ParsedPaper:
    """
    Parse paper using regex - NO LLM. Fast and deterministic.
    
    Title extraction priority (see RSCH_TITLE_FIX.md):
    1. Known title from paper_info registry
    2. PDF metadata (if available and valid)
    3. Regex fallback
    """
    title = paper_info.get("title", "Unknown Title")
    
    # Try PDF metadata as fallback if no known title
    if title == "Unknown Title" and pdf_path and pdf_path.exists():
        try:
            reader = PdfReader(pdf_path)
            if reader.metadata and reader.metadata.title:
                candidate = reader.metadata.title.strip()
                if 5 < len(candidate) < 200 and "arXiv" not in candidate:
                    title = candidate
        except Exception:
            pass
    
    # Extract authors
    author_section = text[:3000]
    author_names = re.findall(r'([A-Z][a-z]+ (?:[A-Z]\. )?[A-Z][a-z]+)(?:\s*[†‡∗*])?', author_section)
    authors = ", ".join(list(set(author_names[:8])))
    
    # Extract abstract
    abstract_match = re.search(
        r'Abstract\s*\n(.*?)(?=\n\s*\d+\s+Introduction|\n\s*1\s+Introduction|\n\s*Keywords)',
        text, re.DOTALL | re.IGNORECASE
    )
    abstract = abstract_match.group(1).strip()[:2000] if abstract_match else ""
    
    # Extract sections
    section_pattern = r'\n(\d+(?:\.\d+)?)\s+([A-Z][^\n]{3,60})\n'
    section_matches = list(re.finditer(section_pattern, text))
    
    sections_summary = "\n".join([
        f"- {m.group(1)} {m.group(2).strip()}"
        for m in section_matches[:15]
    ])
    
    # Extract section text (limited for context window)
    section_texts = []
    for i, match in enumerate(section_matches[:6]):
        start = match.end()
        end = section_matches[i + 1].start() if i + 1 < len(section_matches) else len(text)
        content = text[start:end].strip()[:2500]
        section_texts.append(f"=== {match.group(1)} {match.group(2).strip()} ===\n{content}")
    
    section_text = "\n\n".join(section_texts)
    
    # Extract references
    ref_match = re.search(r'\nReferences\s*\n(.*)', text, re.DOTALL | re.IGNORECASE)
    references = []
    if ref_match:
        ref_text = ref_match.group(1)
        refs = re.split(r'\n\s*\[?\d+\]?\s*', ref_text)
        references = [r.strip()[:200] for r in refs if len(r.strip()) > 20][:30]
    
    return ParsedPaper(
        title=title,
        authors=authors,
        abstract=abstract,
        sections=sections_summary,
        section_text=section_text,
        reference_count=len(references),
        references_sample=references[:10],
    )


async def analyze_single_paper(paper_id: str) -> dict:
    """Analyze a single paper using the paper_analyzer peer machine."""
    paper_info = PAPER_REGISTRY[paper_id]
    
    # Download and parse paper
    pdf_path = ensure_paper_downloaded(paper_id)
    text = extract_text_from_pdf(pdf_path)
    paper = parse_paper_programmatically(text, paper_info, pdf_path=pdf_path)
    
    logger.info(f"Analyzing: {paper.title}")
    logger.info(f"  Abstract: {len(paper.abstract)} chars")
    logger.info(f"  Sections: {len(paper.sections.split(chr(10)))} found")
    
    # Load the paper analyzer machine
    analyzer_config = PAPER_ANALYZER_DIR / 'machine.yml'
    machine = FlatMachine(
        config_file=str(analyzer_config),
        hooks=LoggingHooks()
    )
    
    # Run analysis
    result = await machine.execute(
        input={
            "title": paper.title,
            "authors": paper.authors,
            "abstract": paper.abstract,
            "sections": paper.sections,
            "section_text": paper.section_text,
            "reference_count": paper.reference_count,
            "references_sample": paper.references_sample,
        }
    )
    
    return {
        "paper_id": paper_id,
        "title": paper.title,
        "analysis": result,
    }


async def synthesize_papers(
    paper_ids: List[str],
    research_question: str,
) -> dict:
    """Analyze multiple papers and synthesize findings."""
    
    logger.info("=" * 60)
    logger.info("Multi-Paper Research Synthesizer")
    logger.info("=" * 60)
    logger.info(f"Research Question: {research_question}")
    logger.info(f"Papers to analyze: {paper_ids}")
    logger.info("-" * 60)
    
    # Step 1: Analyze each paper individually
    paper_analyses = []
    for paper_id in paper_ids:
        if paper_id in PAPER_REGISTRY:
            analysis = await analyze_single_paper(paper_id)
            paper_analyses.append(analysis)
        else:
            logger.warning(f"Unknown paper ID: {paper_id}")
    
    logger.info(f"\nAnalyzed {len(paper_analyses)} papers")
    logger.info("-" * 60)
    
    # Step 2: Run synthesis machine
    synthesis_config = CONFIG_DIR / 'machine.yml'
    
    # For now, skip the peer machine invocation and go straight to synthesis agents
    # This is because the full machine->machine pattern needs more work
    # Instead, we'll use the synthesis agents directly
    
    machine = FlatMachine(
        config_file=str(synthesis_config),
        hooks=LoggingHooks()
    )
    
    # Prepare analyses summary for context
    analyses_text = "\n\n".join([
        f"### {a['title']}\n"
        f"Key Findings: {a['analysis'].get('key_findings', 'N/A')}\n"
        f"Summary: {a['analysis'].get('summary', 'N/A')[:500]}"
        for a in paper_analyses
    ])
    
    # Since we already analyzed papers, skip to compare step
    # We need to manually populate the context
    result = {
        "paper_count": len(paper_analyses),
        "paper_analyses": paper_analyses,
        "research_question": research_question,
    }
    
    # Run comparison and synthesis directly using agents
    from flatagents import FlatAgent
    
    # Load comparator
    comparator = FlatAgent(config_file=str(CONFIG_DIR / 'comparator.yml'))
    compare_result = await comparator.call(
        research_question=research_question,
        analyses=analyses_text,
        paper_count=len(paper_analyses),
    )
    
    result["common_themes"] = compare_result.output.get("common_themes", "") if compare_result.output else ""
    result["key_differences"] = compare_result.output.get("key_differences", "") if compare_result.output else ""
    
    # Load gap finder
    gap_finder = FlatAgent(config_file=str(CONFIG_DIR / 'gap_finder.yml'))
    gap_result = await gap_finder.call(
        research_question=research_question,
        common_themes=result["common_themes"],
        key_differences=result["key_differences"],
        analyses=analyses_text,
    )
    
    result["research_gaps"] = gap_result.output.get("research_gaps", "") if gap_result.output else ""
    result["opportunities"] = gap_result.output.get("opportunities", "") if gap_result.output else ""
    
    # Load synthesizer
    synthesizer = FlatAgent(config_file=str(CONFIG_DIR / 'synthesizer.yml'))
    synth_result = await synthesizer.call(
        research_question=research_question,
        paper_count=len(paper_analyses),
        common_themes=result["common_themes"],
        key_differences=result["key_differences"],
        research_gaps=result["research_gaps"],
        opportunities=result["opportunities"],
    )
    
    result["synthesis"] = synth_result.output.get("synthesis", "") if synth_result.output else ""
    
    # Self-judging critique loop
    critic = FlatAgent(config_file=str(CONFIG_DIR / 'critic.yml'))
    for iteration in range(3):
        critique_result = await critic.call(
            research_question=research_question,
            synthesis=result["synthesis"],
            paper_count=len(paper_analyses),
        )
        
        result["quality_score"] = critique_result.output.get("quality_score", 0) if critique_result.output else 0
        result["critique"] = critique_result.output.get("critique", "") if critique_result.output else ""
        
        logger.info(f"Iteration {iteration + 1}: Quality score = {result['quality_score']}/10")
        
        if result["quality_score"] >= 8:
            break
        
        # Improve synthesis based on critique
        synth_result = await synthesizer.call(
            research_question=research_question,
            paper_count=len(paper_analyses),
            common_themes=result["common_themes"],
            key_differences=result["key_differences"],
            research_gaps=result["research_gaps"],
            opportunities=result["opportunities"],
            previous_synthesis=result["synthesis"],
            critique=result["critique"],
        )
        result["synthesis"] = synth_result.output.get("synthesis", result["synthesis"]) if synth_result.output else result["synthesis"]
    
    # Format final report
    formatter = FlatAgent(config_file=str(CONFIG_DIR / 'formatter.yml'))
    format_result = await formatter.call(
        research_question=research_question,
        paper_count=len(paper_analyses),
        common_themes=result["common_themes"],
        key_differences=result["key_differences"],
        research_gaps=result["research_gaps"],
        opportunities=result["opportunities"],
        synthesis=result["synthesis"],
        quality_score=result["quality_score"],
    )
    
    result["synthesis_report"] = format_result.output.get("report", "") if format_result.output else ""
    
    # Save report
    report_path = DATA_DIR / 'synthesis_report.md'
    report_path.write_text(result["synthesis_report"])
    logger.info(f"\n📄 Report saved to: {report_path}")
    
    return result


async def run():
    """Main entry point."""
    # Default: analyze prompt optimization papers
    paper_ids = ["gepa", "mipro", "textgrad"]
    research_question = (
        "What are the most effective techniques for optimizing LLM prompts, "
        "and how do gradient-free methods like GEPA compare to gradient-based approaches?"
    )
    
    result = await synthesize_papers(paper_ids, research_question)
    
    logger.info("=" * 60)
    logger.info("SYNTHESIS COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Papers analyzed: {result['paper_count']}")
    logger.info(f"Quality score: {result['quality_score']}/10")
    logger.info(f"Report: {DATA_DIR / 'synthesis_report.md'}")
    
    return result


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
