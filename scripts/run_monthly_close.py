"""Databricks Python script entry point for the monthly close pipeline."""

from pathlib import Path
import sys


# Databricks compiles Git Python Script Tasks without defining __file__.
# The current code object's filename remains available in both execution modes.
SCRIPT_PATH = Path(globals().get("__file__", sys._getframe().f_code.co_filename)).resolve()
SOURCE_ROOT = SCRIPT_PATH.parents[1] / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from finops_cloud.pipelines.monthly_close import main  # noqa: E402


# Keep this entry point thin: business logic belongs in src/ and remains testable.
if __name__ == "__main__":
    main()
