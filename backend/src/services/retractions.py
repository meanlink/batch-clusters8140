"""批次撤回登记、影响追溯与失效标记。

并发约定：所有可能创建或消费撤回批次的工作流（数据导入、分析完成、
批准、简报创建与归档）都会先取得 ``retraction_lock`` 这一行锁，再读取
撤回登记表。撤回本身也持同一把锁，因此“撤回”与“计算完成 / 到期归档”
互斥而不是事后补救：先提交的一方会看到后提交的一方的最新状态。
"""
import time
from sqlalchemy import select, text
from fastapi import HTTPException
from src.models import Dataset, Delivery, Job, Report, Retraction, RetractionLock

REASON_LIMIT = 500


def normalize_batch_id(value):
    return str(value if value is not None else '').strip().casefold()


def registry_lock(db):
    """Serialize retraction-sensitive work on a single registry row.

    The lock statement is the first statement in the transaction so the
    subsequent reads observe every commit made by a transaction we waited on.
    """
    dialect = db.get_bind().dialect.name
    if dialect == 'sqlite':
        db.execute(text('INSERT OR IGNORE INTO retraction_lock (id) VALUES (1)'))
        # SQLite ignores FOR UPDATE; a no-op write holds its write lock.
        db.execute(text('UPDATE retraction_lock SET id=id WHERE id=1'))
    elif dialect == 'postgresql':
        db.execute(text('INSERT INTO retraction_lock (id) VALUES (1) ON CONFLICT DO NOTHING'))
        db.execute(select(RetractionLock.id).where(RetractionLock.id == 1).with_for_update())
    else:
        # ON DUPLICATE KEY UPDATE takes the exclusive row lock directly, so
        # concurrent first-time callers queue up instead of deadlocking on a
        # shared-lock upgrade.
        db.execute(text('INSERT INTO retraction_lock (id) VALUES (1) ON DUPLICATE KEY UPDATE id=id'))
        db.execute(select(RetractionLock.id).where(RetractionLock.id == 1).with_for_update())


def registry(db):
    """Current retraction registry.

    Callers hold ``retraction_lock`` first. The engine runs MySQL in READ
    COMMITTED, so this plain read observes every retraction committed before
    the lock was granted.
    """
    return {r.batch_key: r for r in db.scalars(select(Retraction).order_by(Retraction.id))}


def rows_matches(records, keys):
    found, seen = [], set()
    for row in records or []:
        key = normalize_batch_id(row.get('batch_id'))
        if key in keys and key not in seen:
            seen.add(key)
            found.append(str(row.get('batch_id')).strip())
    return found


def dataset_matches(dataset, keys):
    """Return the batch ids in ``dataset`` that are on the retraction registry."""
    return rows_matches(dataset.records, keys)


def excluded_keys(job):
    return {normalize_batch_id(v) for v in (job.excluded_batch_ids or [])}


def job_matches(job, keys, dataset=None):
    """Retracted batch ids still used by this analysis (not deliberately excluded)."""
    if not keys or dataset is None:
        return []
    return [b for b in dataset_matches(dataset, keys) if normalize_batch_id(b) not in excluded_keys(job)]


def compute_records(job, dataset):
    """Records a job is allowed to use, i.e. its snapshot minus excluded batches."""
    excluded = excluded_keys(job)
    return [row for row in (dataset.records or [])
            if normalize_batch_id(row.get('batch_id')) not in excluded]


def retraction_reason(db, batch_ids, reg=None):
    reg = reg if reg is not None else registry(db)
    parts = []
    for batch in batch_ids:
        item = reg.get(normalize_batch_id(batch))
        if item:
            parts.append(f'{batch}（{item.reason}）')
    return ('撤回批次：' + '；'.join(parts))[:REASON_LIMIT]


def _merge_batch_ids(existing, found):
    merged = list(existing or [])
    seen = {normalize_batch_id(v) for v in merged}
    for batch in found:
        key = normalize_batch_id(batch)
        if key not in seen:
            seen.add(key)
            merged.append(batch)
    return merged


def _invalidate_job(job, reason, at):
    job.status = 'invalid'
    job.approved = False
    if job.invalidated_at is None:
        job.invalidated_at = at
        job.invalid_reason = reason[:REASON_LIMIT]


def _void_report(report, reason, at):
    if report.voided_at is None:
        report.voided_at = at
        report.void_reason = reason[:REASON_LIMIT]
    report.enabled = False


def _void_delivery(delivery, reason, at):
    if delivery.voided_at is None:
        delivery.voided_at = at
        delivery.void_reason = reason[:REASON_LIMIT]


def apply_impact(db, keys, reg, at):
    """Mark every dataset / analysis / brief touched by ``keys`` as affected.

    Datasets keep their original records; only the quarantine flag is added.
    Existing results on jobs are preserved while the job becomes invalid.
    Issued briefs are retained and marked void.
    """
    datasets = list(db.scalars(select(Dataset)))
    jobs = list(db.scalars(select(Job)))
    touched = {}
    for dataset in datasets:
        found = dataset_matches(dataset, keys)
        if found:
            dataset.retracted_batch_ids = _merge_batch_ids(dataset.retracted_batch_ids, found)
    for job in jobs:
        dataset = next((d for d in datasets if d.id == job.dataset_id), None)
        found = job_matches(job, keys, dataset)
        if not found:
            continue
        if job.status == 'failed':
            # Nothing was produced from the retracted input, so there is no
            # result to revoke; the trace below still lists the analysis.
            continue
        reason = retraction_reason(db, found, reg)
        _invalidate_job(job, reason, at)
        touched[job.id] = reason
    reports = list(db.scalars(select(Report))) if touched else []
    report_ids = set()
    for report in reports:
        if report.job_id in touched:
            _void_report(report, touched[report.job_id], at)
        if report.voided_at is not None:
            report_ids.add(report.id)
    deliveries = list(db.scalars(select(Delivery).where(Delivery.report_id.in_(report_ids))) if report_ids else [])
    for delivery in deliveries:
        report = next((r for r in reports if r.id == delivery.report_id), None)
        _void_delivery(delivery, report.void_reason if report else '关联简报已作废', at)
    return {
        'datasets': sum(1 for d in datasets if dataset_matches(d, keys)),
        'jobs': len(touched),
        'reports': len(report_ids),
        'deliveries': len(deliveries),
    }


def register(db, data, user):
    reason = (data.reason or '').strip()
    if not reason:
        raise HTTPException(422, '请填写撤回原因')
    raw_ids, keys, seen = [], [], set()
    for value in data.batch_ids:
        batch = str(value).strip()
        key = normalize_batch_id(batch)
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        raw_ids.append(batch)
        keys.append(key)
    if not keys:
        raise HTTPException(422, '请填写至少一个批次号')
    registry_lock(db)
    existing = registry(db)
    duplicates = [raw for raw, key in zip(raw_ids, keys) if key in existing]
    if duplicates:
        raise HTTPException(409, f'批次 {"、".join(duplicates)} 已登记撤回，请勿重复登记')
    now = time.time()
    created = []
    for raw, key in zip(raw_ids, keys):
        item = Retraction(batch_id=raw, batch_key=key, reason=reason, actor=user.email,
                          created_by=user.id, created_at=now)
        db.add(item)
        created.append(item)
    db.flush()
    impact = apply_impact(db, set(keys), registry(db), now)
    return created, impact


def impact(db):
    """Read-only trace of every dataset, analysis and brief touched by retractions."""
    reg = registry(db)
    keys = set(reg)
    if not keys:
        return {'retractions': [], 'datasets': [], 'jobs': [], 'reports': [], 'deliveries': []}
    datasets = list(db.scalars(select(Dataset).order_by(Dataset.id)))
    jobs = list(db.scalars(select(Job).order_by(Job.id)))
    by_id = {d.id: d for d in datasets}
    dataset_rows = []
    for dataset in datasets:
        found = dataset_matches(dataset, keys)
        if found:
            dataset_rows.append({
                'id': dataset.id, 'name': dataset.name, 'source': dataset.source,
                'created_at': dataset.created_at, 'matched_batch_ids': found,
                'retracted_batch_ids': dataset.retracted_batch_ids or [],
                'job_ids': [j.id for j in jobs if j.dataset_id == dataset.id],
            })
    job_rows, affected_job_ids = [], set()
    for job in jobs:
        found = job_matches(job, keys, by_id.get(job.dataset_id))
        if found:
            affected_job_ids.add(job.id)
            job_rows.append({
                'id': job.id, 'name': job.name, 'dataset_id': job.dataset_id,
                'status': job.status, 'approved': job.approved,
                'matched_batch_ids': found,
                'excluded_batch_ids': job.excluded_batch_ids or [],
                'replaces_job_id': job.replaces_job_id,
                'invalidated_at': job.invalidated_at,
                'invalid_reason': job.invalid_reason,
                'has_result': bool(job.result),
            })
    report_rows, report_ids = [], set()
    for report in db.scalars(select(Report).order_by(Report.id)):
        if report.job_id in affected_job_ids or report.voided_at is not None:
            report_ids.add(report.id)
            report_rows.append({
                'id': report.id, 'name': report.name, 'job_id': report.job_id,
                'enabled': report.enabled, 'voided_at': report.voided_at,
                'void_reason': report.void_reason,
            })
    delivery_rows = []
    if report_ids:
        for delivery in db.scalars(select(Delivery).where(Delivery.report_id.in_(report_ids)).order_by(Delivery.id)):
            delivery_rows.append({
                'id': delivery.id, 'report_id': delivery.report_id,
                'filename': delivery.filename, 'created_at': delivery.created_at,
                'voided_at': delivery.voided_at, 'void_reason': delivery.void_reason,
            })
    return {
        'retractions': [{
            'id': r.id, 'batch_id': r.batch_id, 'reason': r.reason, 'actor': r.actor,
            'created_at': r.created_at,
        } for r in reg.values()],
        'datasets': dataset_rows,
        'jobs': job_rows,
        'reports': report_rows,
        'deliveries': delivery_rows,
    }


def recompute(db, job, user):
    """Create a replacement analysis that excludes every retracted batch."""
    registry_lock(db)
    dataset = db.get(Dataset, job.dataset_id)
    if dataset is None:
        raise HTTPException(409, '原分析绑定的数据批次已不存在')
    if job.invalidated_at is None:
        raise HTTPException(409, '仅含撤回批次而失效的分析需要剔除重算')
    reg = registry(db)
    found = dataset_matches(dataset, reg)
    excluded = list(found)
    already = excluded_keys(job)
    if not excluded or {normalize_batch_id(b) for b in excluded} <= already:
        raise HTTPException(409, '该分析已剔除全部撤回批次，无需重算')
    existing = db.scalar(select(Job).where(Job.replaces_job_id == job.id))
    if existing is not None:
        raise HTTPException(409, f'该分析已有替代分析 #{existing.id}，请直接查看')
    new_job = Job(
        name=f'{job.name} · 剔除撤回批次', dataset_id=job.dataset_id, params=dict(job.params or {}),
        status='queued', created_by=user.id, created_at=time.time(),
        excluded_batch_ids=excluded, replaces_job_id=job.id,
    )
    db.add(new_job)
    db.flush()
    return new_job
