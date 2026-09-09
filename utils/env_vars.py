from enum import StrEnum
import os

class EnvVarName(StrEnum):
    SECRET="SECRET"
    DATABASE_URL="DATABASE_URL"
    OPENAI_API_KEY="OPENAI_API_KEY"
    SPORTSODDS_API_KEY="SPORTSODDS_API_KEY"
    SPORTSODDS_FIXTURE_DIR="SPORTSODDS_FIXTURE_DIR"

def load_env_var(env_var: EnvVarName):
    return os.environ[env_var.value]

def load_optional_env_var(env_var: EnvVarName) -> str | None:
    """For settings that are absent in production on purpose, rather than missing."""
    return os.environ.get(env_var.value) or None