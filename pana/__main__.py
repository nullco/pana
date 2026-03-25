"""TUI application entry point."""

import logging
import os

from dotenv import load_dotenv

load_dotenv()

_log_file = os.getenv("AGENT_LOG_FILE")
logging.basicConfig(
    level=os.getenv("AGENT_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(_log_file) if _log_file else logging.NullHandler()],
)


def main():
    from pana.main import run

    run()


if __name__ == "__main__":
    main()
