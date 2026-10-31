"""Create .env with a random salt if it does not exist (PRV-1: the salt is never committed)."""
import secrets
from pathlib import Path

env = Path(__file__).resolve().parents[1] / ".env"
if env.exists():
    print(".env already exists - keeping the existing salt")
else:
    example = (env.parent / ".env.example").read_text()
    env.write_text(example.replace("EPISCOPE_SALT=change-me", f"EPISCOPE_SALT={secrets.token_hex(32)}"))
    print("created .env with a fresh random salt (do NOT commit it)")
