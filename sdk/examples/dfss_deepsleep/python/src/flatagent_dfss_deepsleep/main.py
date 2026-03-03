"""
DFSS Deep Sleep — package entry point.

Delegates to the scheduler runner (scheduler_main.py).
The old tree-fanout demo is available as tree_demo.py.
"""
from flatagent_dfss_deepsleep.scheduler_main import main

if __name__ == "__main__":
    main()
