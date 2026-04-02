"""TUI application entry point."""

import argparse
import logging
import os

from dotenv import load_dotenv

load_dotenv()

_log_file = os.getenv("PANA_LOG_FILE")
logging.basicConfig(
    level=os.getenv("PANA_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(_log_file) if _log_file else logging.NullHandler()],
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pana — a minimalist AI coding agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-e",
        "--extension",
        action="append",
        default=[],
        dest="extensions",
        metavar="PATH",
        help=(
            "Load an extension from PATH (.py file or directory with index.py). "
            "May be supplied multiple times."
        ),
    )
    args = parser.parse_args()

    from pana.main import run

    run(extension_paths=args.extensions or None)


if __name__ == "__main__":
    main()
