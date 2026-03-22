"""Entry point for the CFBD coverage audit.

Run from the project root:

    python run_coverage_audit.py

Requires CFBD_API_KEY in .env (loaded automatically via python-dotenv).
Results are printed to stdout and saved to data/audits/cfbd_coverage_audit.csv.
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from ingestion.pull_coverage_audit import run_coverage_audit

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

load_dotenv()


def main() -> None:
    """Load credentials and run the coverage audit."""
    api_key = os.environ.get("CFBD_API_KEY", "")
    if not api_key:
        raise EnvironmentError("CFBD_API_KEY is not set. Add it to your .env file.")

    run_coverage_audit(
        api_key=api_key,
        audit_path=Path("data/audits/cfbd_coverage_audit.csv"),
    )
    print("\nAudit complete. Results saved to data/audits/cfbd_coverage_audit.csv")


if __name__ == "__main__":
    main()
