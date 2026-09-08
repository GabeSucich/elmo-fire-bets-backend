from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from utils.env_vars import EnvVarName, load_env_var

DATABASE_URL = load_env_var(EnvVarName.DATABASE_URL)

engine = create_async_engine(
    DATABASE_URL,
    # Neon closes connections that have been idle, and this app is used in bursts — so a
    # pooled connection is very often dead by the time the next request reaches for it.
    # Without pre-ping that surfaces as a failed request rather than a slow one, which is
    # what the retry-with-sleep loop in routers/auth.py was written to survive.
    pool_pre_ping=True,
    # Retire connections before Neon does, so the reconnect happens on our terms rather
    # than in the middle of someone's request.
    pool_recycle=300,
    pool_size=10,
    max_overflow=5,
)
async_session = async_sessionmaker(engine, expire_on_commit=False)

async def get_db():
    async with async_session() as session:
        yield session