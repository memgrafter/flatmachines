"""
Coding Agent Hooks

Human-in-the-loop hooks for plan and result review.
Preserves history on rejection so agents can learn from feedback.
Also provides exploration tools (tree, ripgrep, read_file) for accurate diffs.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional
from flatmachines import MachineHooks


class CodingAgentHooks(MachineHooks):
    """
    Hooks for human-in-the-loop coding workflow.
    
    Provides:
    - explore_codebase: Gather context about the working directory
    - run_tree: Execute tree command for directory structure
    - run_ripgrep: Search code with ripgrep
    - read_file: Read file contents
    - human_review_plan: Display plan and get approval/feedback
    - human_review_result: Display changes and get approval/feedback
    
    On rejection, preserves the rejected work in history so agents
    can learn from human feedback.
    """
    
    def __init__(self, working_dir: str = "."):
        """Initialize with working directory for exploration."""
        self.working_dir = Path(working_dir).resolve()

    def _get_base_path(self, context: Dict[str, Any]) -> Path:
        """Resolve working directory from context or instance default."""
        working_dir = context.get("working_dir")
        if working_dir:
            return Path(working_dir).expanduser().resolve()
        return self.working_dir

    def _is_within_base(self, base_path: Path, target_path: Path) -> bool:
        """Return True if target_path resolves inside base_path."""
        try:
            target_path.resolve().relative_to(base_path.resolve())
            return True
        except ValueError:
            return False

    def _get_approval_response(self, kind: str) -> Optional[str]:
        """Get optional non-interactive approval response from env vars."""
        import os

        env_key = "CODING_AGENT_APPROVAL_PLAN" if kind == "plan" else "CODING_AGENT_APPROVAL_RESULT"
        value = os.environ.get(env_key)
        if value is None:
            return None
        return value.strip()
    
    def on_state_enter(self, state_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize common numeric fields that may arrive as template strings."""
        for key in ("iteration", "max_iterations", "token_budget", "frozen_token_count"):
            value = context.get(key)
            if isinstance(value, str):
                try:
                    context[key] = int(value)
                except ValueError:
                    pass
        return context

    def on_action(self, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Route actions to their handlers."""
        handlers = {
            "explore_codebase": self._explore_codebase,
            "run_tree": self._run_tree,
            "run_ripgrep": self._run_ripgrep,
            "read_file": self._read_file,
            "read_plan_files": self._read_plan_files,
            "human_review_plan": self._human_review_plan,
            "human_review_result": self._human_review_result,
            "apply_changes": self._apply_changes,
        }
        handler = handlers.get(action_name)
        if handler:
            return handler(context)
        return context
    
    def _run_codebase_ripper(self, context: Dict[str, Any], path: Path) -> Optional[str]:
        """Run codebase-ripper skill and return extracted context text if successful."""
        home = os.environ.get("HOME")
        if not home:
            return None

        ripper_script = Path(home) / ".agents" / "skills" / "codebase-ripper" / "run.sh"
        if not ripper_script.exists():
            return None

        task = str(context.get("task", "Explore this codebase"))
        token_budget_raw = context.get("token_budget", 12000)
        max_iterations_raw = context.get("explorer_iterations", 2)

        try:
            token_budget = int(token_budget_raw)
        except (TypeError, ValueError):
            token_budget = 12000

        try:
            max_iterations = int(max_iterations_raw)
        except (TypeError, ValueError):
            max_iterations = 2

        try:
            result = subprocess.run(
                [
                    "bash",
                    str(ripper_script),
                    task,
                    "-d", str(path),
                    "--token-budget", str(token_budget),
                    "--max-iterations", str(max_iterations),
                    "--json",
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )
        except Exception:
            return None

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            if stderr:
                print(f"⚠️  codebase-ripper failed; falling back to local exploration: {stderr}")
            return None

        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            return None

        extracted = payload.get("context")
        if isinstance(extracted, str) and extracted.strip():
            return extracted.strip()
        return None

    def _explore_codebase(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Gather context about the codebase.

        Preferred path: codebase-ripper skill (parallel out-of-band exploration).
        Fallback path: local tree + README sampling.
        """
        path = self._get_base_path(context)

        ripper_context = self._run_codebase_ripper(context, path)
        if ripper_context:
            context["codebase_context"] = ripper_context
            context["explorer_source"] = "codebase-ripper"
            return context

        context_parts = []

        # Get directory structure
        try:
            result = subprocess.run(
                ["tree", "-L", "3", "-I", "__pycache__|node_modules|.git|.venv|*.pyc"],
                cwd=path,
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                context_parts.append(f"## Directory Structure\n```\n{result.stdout}\n```")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            # tree not available, use ls
            try:
                result = subprocess.run(
                    ["ls", "-la"],
                    cwd=path,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                context_parts.append(f"## Files\n```\n{result.stdout}\n```")
            except Exception:
                context_parts.append(f"## Working Directory\n{path}")

        # Look for README
        for readme_name in ["README.md", "README.txt", "README"]:
            readme_path = path / readme_name
            if readme_path.exists():
                try:
                    content = readme_path.read_text()[:2000]  # Limit size
                    context_parts.append(f"## {readme_name}\n{content}")
                    break
                except Exception:
                    pass

        context["codebase_context"] = "\n\n".join(context_parts) or f"Working directory: {path}"
        context["explorer_source"] = "fallback-local"
        return context
    
    def _run_tree(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute tree command.
        
        Expects: context.action_command (tree command or path)
        Returns: context.latest_output, updated tree_outputs
        """
        cmd = context.get("action_command", "")
        cwd = self._get_base_path(context)

        # If just a path, prepend tree command
        if not cmd or not cmd.strip().startswith("tree"):
            path = cmd.strip() if cmd else "."
            cmd = f"tree -L 3 --noreport {path}"

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=30
            )
            output = result.stdout or result.stderr
        except subprocess.TimeoutExpired:
            output = "Error: tree command timed out"
        except Exception as e:
            output = f"Error: {e}"

        context["latest_output"] = output
        context["latest_action"] = "tree"

        # Append to tree_outputs
        tree_outputs = context.get("tree_outputs", [])
        tree_outputs.append({"command": cmd, "output": output})
        context["tree_outputs"] = tree_outputs

        return context

    def _run_ripgrep(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute ripgrep command.
        
        Expects: context.action_command (rg command or pattern)
        Returns: context.latest_output, updated rg_results
        """
        cmd = context.get("action_command", "")
        cwd = self._get_base_path(context)

        # If just a pattern, prepend rg command
        if not cmd or not cmd.strip().startswith("rg"):
            pattern = cmd.strip() if cmd else "TODO"
            cmd = f"rg '{pattern}' --type-add 'code:*.{{py,js,ts,yml,yaml}}' --type code"

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=60
            )
            output = result.stdout or result.stderr or "(no matches)"
        except subprocess.TimeoutExpired:
            output = "Error: ripgrep command timed out"
        except Exception as e:
            output = f"Error: {e}"

        # Truncate if too large
        if len(output) > 50000:
            output = output[:50000] + "\n... (truncated)"

        context["latest_output"] = output
        context["latest_action"] = "rg"

        # Append to rg_results
        rg_results = context.get("rg_results", [])
        rg_results.append({"command": cmd, "output": output})
        context["rg_results"] = rg_results

        return context

    def _read_file(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Read file contents.
        
        Expects: context.action_command (file path)
        Returns: context.latest_output, updated file_contents
        """
        filepath = context.get("action_command", "")
        base_path = self._get_base_path(context)

        if not filepath:
            context["latest_output"] = "Error: no file path specified"
            context["latest_action"] = "read"
            return context

        # Resolve path relative to working dir (unless already absolute)
        candidate_path = Path(filepath)
        full_path = candidate_path if candidate_path.is_absolute() else (base_path / candidate_path)

        # Security: ensure path is within working dir
        if not self._is_within_base(base_path, full_path):
            context["latest_output"] = "Error: path outside working directory"
            context["latest_action"] = "read"
            return context

        full_path = full_path.resolve()

        try:
            content = full_path.read_text()
            # Truncate if too large
            if len(content) > 100000:
                content = content[:100000] + "\n... (truncated)"
            output = content
        except FileNotFoundError:
            output = f"Error: file not found: {filepath}"
        except Exception as e:
            output = f"Error reading file: {e}"

        context["latest_output"] = output
        context["latest_action"] = "read"

        # Add to file_contents
        file_contents = context.get("file_contents", {})
        file_contents[filepath] = output
        context["file_contents"] = file_contents

        return context
    
    def _read_plan_files(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract file paths from the plan and read them for the coder.
        
        Looks for paths in the plan text (e.g., src/foo.py, ./lib/bar.js)
        and reads each file so the coder has exact content for SEARCH/REPLACE.
        """
        import re
        
        plan_raw = context.get("plan", "")
        if isinstance(plan_raw, dict) and 'content' in plan_raw:
            plan = plan_raw['content']
        else:
            plan = str(plan_raw)
        
        base_path = self._get_base_path(context)
        
        # Extract file paths from plan - look for path-like patterns
        # Matches: src/file.py, ./lib/foo.js, path/to/file.ts, etc.
        path_pattern = r'(?:^|\s|`|\[|\()(\.?/?(?:[\w.-]+/)*[\w.-]+\.(?:py|js|ts|jsx|tsx|yml|yaml|json|md|txt|sh|go|rs|rb|java|c|cpp|h|hpp|css|html|sql))(?:\s|$|`|\]|\)|:)'
        
        matches = re.findall(path_pattern, plan, re.MULTILINE)
        # Deduplicate and normalize
        paths = list(dict.fromkeys([p.lstrip('./') for p in matches]))
        
        file_contents = context.get("file_contents", {})
        files_read = []
        
        for filepath in paths[:20]:  # Limit to 20 files to avoid overwhelming context
            full_path = (base_path / filepath).resolve()

            # Security check
            if not self._is_within_base(base_path, full_path):
                continue
            
            # Read file
            try:
                if full_path.exists() and full_path.is_file():
                    content = full_path.read_text()
                    # Truncate very large files
                    if len(content) > 50000:
                        content = content[:50000] + "\n... (truncated)"
                    file_contents[filepath] = content
                    files_read.append(filepath)
            except Exception:
                pass
        
        context["file_contents"] = file_contents
        
        # Log what was read
        print(f"\n📂 Read {len(files_read)} files for coder context:")
        for f in files_read:
            print(f"   - {f}")
        
        return context
    
    def _human_review_plan(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Display the plan and get human approval or feedback.
        
        On rejection, saves the plan to history with feedback so
        the planner can learn from it.
        """
        plan_raw = context.get("plan", "")
        
        # FlatAgent wraps text in {'content': ...} - extract it
        if isinstance(plan_raw, dict) and 'content' in plan_raw:
            plan = plan_raw['content']
        else:
            plan = plan_raw
        
        print("\n" + "=" * 70)
        print("📋 PLAN REVIEW")
        print("=" * 70)
        
        print(f"\n📝 Task: {context.get('task', 'Unknown')}\n")
        
        # Display plan as text (show full content)
        if plan and str(plan).strip():
            print("-" * 70)
            print(str(plan))
            print("-" * 70)
        else:
            print("[WARNING] No plan content received")
        
        print("\n" + "-" * 70)
        response = self._get_approval_response("plan")
        if response is None:
            response = input("Approve plan? (y/yes to approve, or enter feedback): ").strip()

        if response.lower() in ("y", "yes", "", "approved"):
            context["plan_approved"] = True
            context["human_feedback"] = None
            print("✅ Plan approved!")
        else:
            context["plan_approved"] = False
            context["human_feedback"] = response
            
            # Preserve rejected plan in history
            plan_history = context.get("plan_history", [])
            plan_history.append({
                "content": plan,
                "feedback": response
            })
            context["plan_history"] = plan_history
            print(f"🔄 Feedback recorded. Revising plan...")
        
        print("=" * 70 + "\n")
        return context
    
    def _human_review_result(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Display the changes and get human approval or feedback.
        
        On rejection, saves changes to history with feedback so
        the coder can learn from it.
        """
        changes_raw = context.get("changes", "")
        issues_raw = context.get("issues", "")
        review_summary_raw = context.get("review_summary", "")
        
        # FlatAgent wraps text in {'content': ...} - extract it
        if isinstance(changes_raw, dict) and 'content' in changes_raw:
            changes = changes_raw['content']
        else:
            changes = changes_raw
            
        if isinstance(issues_raw, dict) and 'content' in issues_raw:
            issues = issues_raw['content']
        else:
            issues = issues_raw
            
        if isinstance(review_summary_raw, dict) and 'content' in review_summary_raw:
            review_summary = review_summary_raw['content']
        else:
            review_summary = review_summary_raw
        
        print("\n" + "=" * 70)
        print("🔍 RESULT REVIEW")
        print("=" * 70)
        
        print(f"\n📝 Task: {context.get('task', 'Unknown')}")
        print(f"🔄 Iteration: {context.get('iteration', '?')}\n")
        
        # Display changes as text
        if changes and str(changes).strip():
            print("Proposed Changes:")
            print("-" * 70)
            print(str(changes))
            print("-" * 70)
        else:
            print("[WARNING] No changes content received")
        
        # Display reviewer findings
        if issues and str(issues).strip():
            print(f"\n📊 Reviewer Assessment:")
            print(str(issues))
        
        if review_summary and str(review_summary).strip():
            print(f"\n📊 Review: {review_summary}")
        
        print("\n" + "-" * 70)
        response = self._get_approval_response("result")
        if response is None:
            response = input("Approve changes? (y/yes to approve, or enter feedback): ").strip()

        if response.lower() in ("y", "yes", "", "approved"):
            context["result_approved"] = True
            context["human_feedback"] = None
            print("✅ Changes approved!")
        else:
            context["result_approved"] = False
            context["human_feedback"] = response
            
            # Preserve rejected changes in history
            changes_history = context.get("changes_history", [])
            changes_history.append({
                "content": changes,
                "feedback": response,
                "issues": issues
            })
            context["changes_history"] = changes_history
            print(f"🔄 Feedback recorded. Revising changes...")
        
        print("=" * 70 + "\n")
        return context
    
    def _parse_diffs(self, text: str) -> List[Dict[str, Any]]:
        """
        Parse SEARCH/REPLACE blocks into file operations.
        
        Format:
            ```language
            filepath
            <<<<<<< SEARCH
            content to find (empty for new files)
            =======
            replacement content
            >>>>>>> REPLACE
            ```
        
        Requirements:
        - SEARCH must match file content exactly (character for character)
        - Empty SEARCH section creates a new file
        - Empty REPLACE section deletes the matched content
        - Only first match is replaced per block
        - Multiple blocks can target the same file
        - Duplicate blocks (same file+search): LAST one wins
        - Files containing ``` must use ```` (quad backticks)
        - If SEARCH matches multiple locations, operation is rejected
        - Files that become empty after edits are deleted
        
        Returns:
            List of operation dicts with keys:
            - path: file path
            - action: 'create' or 'modify'
            - content: for create
            - search, replace, is_diff: for modify
        """
        import re
        
        # More flexible pattern - handles empty SEARCH for new files
        # The key fix: (.*?) between SEARCH and ======= without requiring surrounding \n
        # Quad backtick pattern
        quad_pattern = r'````([a-zA-Z]*)\n([^\n]+)\n<<<<<<< SEARCH\n?(.*?)\n?=======\n(.*?)\n>>>>>>> REPLACE\s*````'
        # Triple backtick pattern  
        triple_pattern = r'```([a-zA-Z]*)\n([^\n]+)\n<<<<<<< SEARCH\n?(.*?)\n?=======\n(.*?)\n>>>>>>> REPLACE\s*```'
        
        blocks_by_key = {}
        
        # Try quad backticks first
        for match in re.finditer(quad_pattern, text, re.DOTALL):
            filepath = match.group(2).strip()
            search_content = match.group(3)
            replace_content = match.group(4)
            key = (filepath, search_content)
            
            if not search_content.strip():
                blocks_by_key[key] = {'path': filepath, 'action': 'create', 'content': replace_content}
            else:
                blocks_by_key[key] = {'path': filepath, 'action': 'modify', 'search': search_content, 'replace': replace_content, 'is_diff': True}
        
        # Then triple backticks
        for match in re.finditer(triple_pattern, text, re.DOTALL):
            filepath = match.group(2).strip()
            search_content = match.group(3)
            replace_content = match.group(4)
            key = (filepath, search_content)
            
            if not search_content.strip():
                blocks_by_key[key] = {'path': filepath, 'action': 'create', 'content': replace_content}
            else:
                blocks_by_key[key] = {'path': filepath, 'action': 'modify', 'search': search_content, 'replace': replace_content, 'is_diff': True}
        return list(blocks_by_key.values())
    
    def _apply_search_replace(self, original: str, diff_content: str) -> str:
        """Apply SEARCH/REPLACE blocks to original content."""
        import re
        
        result = original
        
        # Find all SEARCH/REPLACE blocks
        pattern = r'<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE'
        
        for match in re.finditer(pattern, diff_content, re.DOTALL):
            search = match.group(1)
            replace = match.group(2)
            
            if search in result:
                result = result.replace(search, replace, 1)
        
        return result
    
    def _apply_changes(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply approved changes to the filesystem.
        
        Parses aider-style diff output and applies changes.
        """
        from pathlib import Path
        
        changes_raw = context.get("changes", "")
        
        # FlatAgent wraps text in {'content': ...} - extract it
        if isinstance(changes_raw, dict) and 'content' in changes_raw:
            changes = changes_raw['content']
        else:
            changes = changes_raw
            
        working_dir = context.get("working_dir", ".")
        base_path = Path(working_dir).expanduser().resolve()
        
        # Use user's actual cwd for safety check
        user_cwd = context.get("user_cwd")
        safety_base = Path(user_cwd).resolve() if user_cwd else base_path
        
        print("\n" + "=" * 70)
        print("📝 APPLYING CHANGES")
        print("=" * 70 + "\n")
        
        # Parse the raw text output
        if isinstance(changes, str) and changes.strip():
            operations = self._parse_diffs(changes)
        elif isinstance(changes, dict) and 'files' in changes:
            # Legacy JSON format fallback
            operations = changes.get('files', [])
        else:
            operations = []
        
        applied = []
        errors = []
        
        for op in operations:
            if not isinstance(op, dict):
                continue
                
            path = op.get("path", "")
            action = op.get("action", "")
            content = op.get("content", "")
            search = op.get("search", "")
            replace = op.get("replace", "")
            is_diff = op.get("is_diff", False)
            
            if not path:
                continue
            
            # Resolve path relative to working directory
            file_path = (base_path / path).resolve()
            
            # SAFETY CHECK: Ensure file is within user's actual cwd
            try:
                file_path.relative_to(safety_base)
            except ValueError:
                errors.append(f"🚫 BLOCKED: Path outside allowed directory: {path}")
                print(f"  🚫 BLOCKED: {path} (outside {safety_base})")
                continue
            
            try:
                if action == "create":
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.write_text(content)
                    applied.append(f"➕ Created: {path}")
                    print(f"  ➕ Created: {path}")
                    
                elif action == "modify":
                    if file_path.exists():
                        original = file_path.read_text()
                        if is_diff and search:
                            # Count matches to detect ambiguity
                            match_count = original.count(search)
                            if match_count == 0:
                                errors.append(f"SEARCH not found in: {path}")
                                print(f"  ⚠️  SEARCH not found: {path}")
                            elif match_count > 1:
                                # Find line numbers of all matches
                                lines = original.split('\n')
                                match_lines = []
                                pos = 0
                                for i, line in enumerate(lines, 1):
                                    if search.split('\n')[0] in line:
                                        match_lines.append(i)
                                errors.append(f"Multiple matches ({match_count}) in {path} at lines: {match_lines}")
                                print(f"  ⚠️  AMBIGUOUS: {match_count} matches in {path} at lines {match_lines}")
                            else:
                                # Exactly one match - apply it
                                new_content = original.replace(search, replace, 1)
                                
                                # Delete file if it becomes empty
                                if not new_content.strip():
                                    file_path.unlink()
                                    applied.append(f"🗑️  Deleted (empty): {path}")
                                    print(f"  🗑️  Deleted (empty): {path}")
                                else:
                                    file_path.write_text(new_content)
                                    applied.append(f"✏️  Modified: {path}")
                                    print(f"  ✏️  Modified: {path}")
                        else:
                            # Full content replacement
                            file_path.write_text(content)
                            applied.append(f"✏️  Modified: {path}")
                            print(f"  ✏️  Modified: {path}")
                    else:
                        errors.append(f"File not found for modify: {path}")
                        print(f"  ⚠️  File not found: {path}")
                        
                elif action == "delete":
                    if file_path.exists():
                        file_path.unlink()
                        applied.append(f"🗑️  Deleted: {path}")
                        print(f"  🗑️  Deleted: {path}")
                    else:
                        errors.append(f"File not found for delete: {path}")
                        print(f"  ⚠️  File not found: {path}")
                else:
                    errors.append(f"Unknown action '{action}' for: {path}")
                    print(f"  ⚠️  Unknown action '{action}': {path}")
                    
            except Exception as e:
                errors.append(f"Error with {path}: {str(e)}")
                print(f"  ❌ Error: {path} - {e}")
        
        context["applied_changes"] = applied
        context["apply_errors"] = errors
        
        print(f"\n✅ Applied {len(applied)} changes")
        if errors:
            print(f"⚠️  {len(errors)} errors")
        print("=" * 70 + "\n")
        
        return context

