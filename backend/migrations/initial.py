from sqlalchemy import inspect, text
from src.config.database import Base, engine
from src import models

# Columns introduced after the first release. ``create_all`` only creates
# missing tables, so existing deployments need these additive migrations.
COLUMNS = {
    'datasets': [('retracted_batch_ids', 'JSON')],
    'jobs': [
        ('excluded_batch_ids', 'JSON'),
        ('replaces_job_id', 'INTEGER'),
        ('invalidated_at', 'DOUBLE'),
        ('invalid_reason', "VARCHAR(500) NOT NULL DEFAULT ''"),
    ],
    'reports': [
        ('voided_at', 'DOUBLE'),
        ('void_reason', "VARCHAR(500) NOT NULL DEFAULT ''"),
    ],
    'deliveries': [
        ('voided_at', 'DOUBLE'),
        ('void_reason', "VARCHAR(500) NOT NULL DEFAULT ''"),
    ],
}


def _add_columns():
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in COLUMNS.items():
            if table not in existing_tables:
                continue
            present = {c['name'] for c in inspector.get_columns(table)}
            for name, ddl in columns:
                if name in present:
                    continue
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))


def migrate():
    Base.metadata.create_all(engine)
    _add_columns()


if __name__ == '__main__':
    migrate()
