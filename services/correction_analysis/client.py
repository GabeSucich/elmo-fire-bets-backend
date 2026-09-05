from functools import lru_cache

from openai import AsyncOpenAI

from utils.env_vars import EnvVarName, load_env_var


class CorrectionAnalysisError(Exception):
    """Raised when the analysis models cannot produce a usable result."""


@lru_cache(maxsize=1)
def get_client() -> AsyncOpenAI:
    """Built lazily so importing the router does not require the key to be set."""
    return AsyncOpenAI(api_key=load_env_var(EnvVarName.OPENAI_API_KEY))
