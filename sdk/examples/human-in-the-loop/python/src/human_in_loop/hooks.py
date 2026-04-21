"""
Human-in-the-Loop Hooks

Provides the human_review action that pauses execution
for human approval or feedback.
"""

from typing import Any, Dict
from flatmachines import MachineHooks


class HumanInLoopHooks(MachineHooks):
    """
    Hooks for human-in-the-loop workflow.
    
    The human_review action pauses execution and prompts the user
    for approval or feedback in the terminal.
    """
    
    def on_action(self, state_name: str, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Handle custom actions."""
        if action_name == "human_review":
            return self._human_review(context)
        return context
    
    def _human_review(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Pause for human review of the current draft.
        
        Displays the draft and prompts for:
        - 'y' or 'yes' to approve
        - Any other input becomes feedback for revision
        """
        context["revision_count"] = int(context.get("revision_count", 0) or 0) + 1

        print("\n" + "=" * 60)
        print("HUMAN REVIEW REQUIRED")
        print("=" * 60)
        print(f"\nRevision #{context.get('revision_count', 1)}")
        print("\nCurrent Draft:")
        print("-" * 40)
        print(context.get("draft", "(No draft yet)"))
        print("-" * 40)
        
        response = input("\nApprove? (y/yes to approve, or enter feedback): ").strip()
        
        if response.lower() in ("y", "yes", ""):
            context["human_approved"] = True
            context["human_feedback"] = None
            print("✓ Draft approved!")
        else:
            context["human_approved"] = False
            context["human_feedback"] = response
            print(f"→ Feedback recorded. Requesting revision...")
        
        print("=" * 60 + "\n")
        return context
