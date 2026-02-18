from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from utils.env_vars import EnvVarName, load_env_var

DATABASE_URL = load_env_var(EnvVarName.DATABASE_URL)

engine = create_async_engine(DATABASE_URL)
async_session = async_sessionmaker(engine, expire_on_commit=False)

async def get_db():
    async with async_session() as session:
        yield session