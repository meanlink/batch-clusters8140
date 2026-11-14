from sqlalchemy import String, JSON, Double, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class Job(Base):
    __tablename__ = 'jobs'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default='queued')
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(String(1000), default='')
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    # Batch ids deliberately left out of this computation. Used by the
    # "recompute excluding retracted batches" flow so the original data
    # snapshot stays untouched while the new analysis is reproducible.
    excluded_batch_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Original analysis this job replaces after a retraction.
    replaces_job_id: Mapped[int | None] = mapped_column(nullable=True)
    invalidated_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    invalid_reason: Mapped[str] = mapped_column(String(500), default='')
