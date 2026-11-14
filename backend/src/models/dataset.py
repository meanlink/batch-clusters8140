from sqlalchemy import String, JSON, Double
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class Dataset(Base):
    __tablename__ = 'datasets'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    source: Mapped[str] = mapped_column(String(200), default='manual.json')
    records: Mapped[list] = mapped_column(JSON)
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[float] = mapped_column(Double)
    # Batch ids present in this snapshot that are on the retraction registry.
    # Kept on the dataset so an import that arrives after the retraction is
    # visibly quarantined without touching the original records.
    retracted_batch_ids: Mapped[list] = mapped_column(JSON, default=list)
