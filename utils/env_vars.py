from enum import StrEnum
import os

class EnvVarName(StrEnum):
    SECRET="SECRET"
    DATABASE_URL="DATABASE_URL"
    OPENAI_API_KEY="OPENAI_API_KEY"

def load_env_var(env_var: EnvVarName):
    return os.environ[env_var.value]