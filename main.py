"""
main.py — Entrypoint.
Loads .env, then delegates to bot.run_with_restart().
"""

from dotenv import load_dotenv

# Load .env BEFORE any other import reads os.getenv()
load_dotenv()

from bot import run_with_restart  # noqa: E402

if __name__ == "__main__":
    run_with_restart()
