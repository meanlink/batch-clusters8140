from sqlalchemy import String, Double, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class Retraction(Base):
    """A batch number that calibration review has declared untrustworthy.

    ``batch_key`` is the trimmed, case-folded form used to match batch numbers
    in every dataset, including datasets imported after the retraction.
    """
    __tablename__ = 'retractions'
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(80))
    batch_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    reason: Mapped[str] = mapped_column(String(500))
    actor: Mapped[str] = mapped_column(String(150))
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)


class RetractionLock(Base):
    """Singleton row used to serialize retraction against ingest/approval/delivery.

    Every workflow that could create or consume a retracted batch takes this
    row with ``SELECT ... FOR UPDATE`` before reading the retraction registry.
    That makes "retract" and "compute finished / archive due" mutually
    exclusive instead of relying on a best-effort post-check.
    """
    __tablename__ = 'retraction_lock'
    id: Mapped[int] = mapped_column(primary_key=True)
