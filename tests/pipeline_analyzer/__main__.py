"""Entry point: python -m tests.pipeline_analyzer"""

import sys
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from tests.pipeline_analyzer.analyzer_ui import main

if __name__ == "__main__":
    main()
