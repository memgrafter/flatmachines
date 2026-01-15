"""
Multi-Chapter Story Writer Demo for FlatAgents (Machine Topology + Checkpoint/Resume).

Demonstrates:
- Machine Peering: Main machine launches and coordinates chapter-writing peer machines
- Checkpoint/Resume: Stop mid-story, resume days later
- Iterative Refinement: Draft → Critique → Revise loop per chapter

Usage:
    python -m story_writer.main
    ./run.sh
"""

import asyncio
import json
from pathlib import Path

from flatagents import FlatMachine, LoggingHooks, setup_logging, get_logger

setup_logging(level='INFO')
logger = get_logger(__name__)


async def run(
    genre: str = "science fiction",
    premise: str = "A librarian discovers books can transport readers into their stories",
    num_chapters: int = 2,
    resume_id: str = None
):
    """
    Run the multi-chapter story writer.

    Args:
        genre: Story genre (e.g., "science fiction", "fantasy", "mystery")
        premise: The story premise/hook
        num_chapters: Number of chapters to write
        resume_id: Optional execution ID to resume from checkpoint
    """
    logger.info("=" * 60)
    logger.info("Multi-Chapter Story Writer (Machine Topology + Checkpoint)")
    logger.info("=" * 60)

    config_path = Path(__file__).parent.parent.parent / 'config' / 'machine.yml'
    machine = FlatMachine(
        config_file=str(config_path),
        hooks=LoggingHooks()
    )

    logger.info(f"Machine: {machine.machine_name}")
    logger.info(f"Genre: {genre}")
    logger.info(f"Premise: {premise}")
    logger.info(f"Chapters: {num_chapters}")
    if resume_id:
        logger.info(f"Resuming from: {resume_id}")
    logger.info("-" * 60)

    result = await machine.execute(
        input={
            "genre": genre,
            "premise": premise,
            "num_chapters": num_chapters
        }
    )

    logger.info("=" * 60)
    logger.info("STORY COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Title: {result.get('title', 'Untitled')}")
    logger.info(f"Chapters Written: {result.get('chapters_completed', 0)}")
    
    # Show first 300 chars of each chapter
    chapters = result.get('chapters', [])
    
    # Parse chapters - may be nested JSON strings from template rendering
    def flatten_chapters(data):
        """Recursively parse JSON strings and flatten nested lists."""
        if isinstance(data, str):
            try:
                data = json.loads(data)
                return flatten_chapters(data)  # Recurse in case of nested strings
            except json.JSONDecodeError:
                return [data]  # It's just text, wrap it
        if isinstance(data, list):
            result = []
            for item in data:
                flattened = flatten_chapters(item)
                if isinstance(flattened, list):
                    result.extend(flattened)
                else:
                    result.append(flattened)
            return result
        return [str(data)]
    
    chapters = flatten_chapters(chapters)
    
    for i, chapter in enumerate(chapters[:3], 1):
        logger.info(f"\n--- Chapter {i} Preview ---")
        logger.info(f"{chapter[:300]}..." if len(chapter) > 300 else chapter)

    logger.info("\n--- Statistics ---")
    logger.info(f"Execution ID: {machine.execution_id}")
    logger.info(f"Total API calls: {machine.total_api_calls}")
    logger.info(f"Estimated cost: ${machine.total_cost:.4f}")

    # Save the story to a file
    output_dir = Path(__file__).parent.parent.parent / 'output'
    output_dir.mkdir(exist_ok=True)
    
    title = result.get('title', 'Untitled')
    safe_title = "".join(c if c.isalnum() or c in ' -_' else '' for c in title).strip().replace(' ', '_')
    output_file = output_dir / f"{safe_title}.md"
    
    with open(output_file, 'w') as f:
        f.write(f"# {title}\n\n")
        f.write(f"*Genre: {genre}*\n\n")
        f.write(f"*Premise: {premise}*\n\n")
        f.write("---\n\n")
        
        # chapters was already parsed above
        for i, chapter in enumerate(chapters, 1):
            # Clean up the chapter text
            chapter_text = str(chapter)
            # Replace escaped newlines with actual newlines
            chapter_text = chapter_text.replace('\\n', '\n')
            # Strip any leading/trailing brackets or quotes
            chapter_text = chapter_text.strip("[]'\"")
            
            f.write(f"## Chapter {i}\n\n")
            f.write(f"{chapter_text}\n\n")
    
    logger.info(f"\n📖 Story saved to: {output_file}")

    return result


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
