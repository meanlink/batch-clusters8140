import time, json, logging
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Job, Dataset, Report
from src.services.business import analyze
from src.services.reports import deliver
from src.services import retractions as retraction_service
from src.services.audit import record
logging.basicConfig(level=logging.INFO)


def _start(job_id):
    """Claim a queued job for computation, refusing already-retracted input."""
    with Session() as db:
        retraction_service.registry_lock(db)
        j = db.get(Job, job_id)
        if not j or j.status != 'queued':
            return None
        dataset = db.get(Dataset, j.dataset_id)
        if retraction_service.job_matches(j, set(retraction_service.registry(db)), dataset):
            retraction_service._invalidate_job(j, '撤回批次在排队期间登记，任务未执行', time.time())
            record(db, 'worker', 'job.invalidated', {'id': j.id})
            db.commit()
            return None
        j.status = 'running'
        db.commit()
        return {'params': dict(j.params or {}), 'excluded': retraction_service.excluded_keys(j),
                'records': list(dataset.records or [])}


def _finish(job_id, result, error):
    """Commit the outcome only if no retraction invalidated the job meanwhile.

    The registry lock is re-taken here, so a retraction that started during the
    computation is either ordered before this commit (and the result is
    discarded) or after it (and its impact pass invalidates the job).
    """
    with Session() as db:
        retraction_service.registry_lock(db)
        j = db.get(Job, job_id)
        if not j:
            return
        if j.invalidated_at or j.status == 'invalid':
            record(db, 'worker', 'job.discarded', {'id': job_id, 'reason': '撤回批次与计算并发'})
            db.commit()
            return
        dataset = db.get(Dataset, j.dataset_id)
        if retraction_service.job_matches(j, set(retraction_service.registry(db)), dataset):
            retraction_service._invalidate_job(j, '撤回批次与计算并发，结果不采纳', time.time())
            record(db, 'worker', 'job.discarded', {'id': job_id, 'reason': '撤回批次与计算并发'})
            db.commit()
            return
        if error is None:
            j.result = result
            j.status = 'completed'
            j.finished_at = time.time()
            record(db, 'worker', 'job.completed', {'id': j.id})
        else:
            j.status = 'failed'
            j.error = error[:990]
            j.finished_at = time.time()
            record(db, 'worker', 'job.failed', {'id': j.id, 'error': j.error})
        db.commit()


def execute(job_id):
    context = _start(job_id)
    if context is None:
        return
    try:
        records = [row for row in context['records']
                   if retraction_service.normalize_batch_id(row.get('batch_id')) not in context['excluded']]
        result = analyze(records, context['params'])
        json.dumps(result, allow_nan=False)
        _finish(job_id, result, None)
    except Exception as e:
        logging.exception('Analysis failed')
        _finish(job_id, None, str(e))


def tick():
    with Session() as db:
        queued = list(db.scalars(select(Job.id).where(Job.status == 'queued').limit(3)))
    for job_id in queued:
        execute(job_id)
    with Session() as db:
        # Hold the registry lock for the whole due-brief pass so a retraction
        # either applies before delivery starts or waits until it finishes.
        retraction_service.registry_lock(db)
        for r in db.scalars(select(Report).where(Report.enabled == True, Report.next_run <= time.time(), Report.voided_at.is_(None))):
            d = deliver(db, r)
            if d:
                record(db, 'worker', 'report.delivered', {'id': r.id, 'delivery': d.id})
        db.commit()


def main():
    r = Redis.from_url(REDIS_URL, socket_timeout=3)
    # This Compose stack has a single worker. A crash must not strand its jobs.
    with Session() as db:
        for j in db.scalars(select(Job).where(Job.status == 'running')):
            j.status = 'queued'
            record(db, 'worker', 'job.recovered', {'id': j.id})
        db.commit()
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item = r.blpop('analysis:queue', timeout=1)
            if item:
                execute(int(item[1]))
            tick()
        except Exception:
            logging.exception('Worker retry'); time.sleep(2)


if __name__ == '__main__':
    main()
