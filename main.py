import logging
import os

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=os.getenv("AGENT_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


if __name__ == "__main__":
    from app.tui.mini import run

    run()
