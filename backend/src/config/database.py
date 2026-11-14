from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .settings import DATABASE_URL

class Base(DeclarativeBase):
    pass

# Retraction correctness relies on statement-level snapshots: a request first
# authenticates (a plain read opens the transaction) and only later takes the
# retraction lock. Under MySQL's default REPEATABLE READ the later reads would
# still see the pre-lock snapshot, so a concurrently committed retraction or a
# concurrently imported snapshot could be missed. READ COMMITTED gives each
# statement the latest committed rows once the lock is held.
_engine_args = {'pool_pre_ping': True, 'pool_recycle': 1800}
if DATABASE_URL.startswith('mysql'):
    _engine_args['isolation_level'] = 'READ COMMITTED'
engine = create_engine(DATABASE_URL, **_engine_args)
Session = sessionmaker(engine, expire_on_commit=False)

def get_db():
    with Session() as db:
        yield db
