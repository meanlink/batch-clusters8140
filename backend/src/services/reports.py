import time, os, csv, io, hashlib, json
from fastapi import HTTPException
from src.models import Dataset, Job, Report, Delivery
from src.config.settings import ARTIFACT_DIR
from src.services import retractions as retraction_service


def create(db, data):
    retraction_service.registry_lock(db)
    j = db.get(Job, data.job_id)
    if not j or j.status != 'completed' or not j.approved or j.invalidated_at:
        raise HTTPException(409, '请先选择已完成且获批准的分析结果')
    keys = set(retraction_service.registry(db))
    if retraction_service.job_matches(j, keys, db.get(Dataset, j.dataset_id)):
        raise HTTPException(409, '该分析含已撤回批次，不能创建简报；请先从受影响分析发起剔除重算')
    r = Report(name=data.name, job_id=j.id, destination=data.destination,
               interval_seconds=data.interval_seconds, next_run=time.time() + data.delay_seconds, enabled=True)
    db.add(r); db.flush()
    return r


def deliver(db, report):
    """Write one due brief. Caller holds the registry lock.

    Returns None when the brief must not be issued (job no longer valid, brief
    voided, or a retraction committed after the report row was read).
    """
    retraction_service.registry_lock(db)
    j = db.get(Job, report.job_id)
    if not j or not j.approved or j.invalidated_at or j.status != 'completed':
        # Keep the schedule from retrying forever; the brief itself is retained
        # for audit and marked void instead of deleted.
        if j is not None and (j.invalidated_at or j.status == 'invalid'):
            retraction_service._void_report(report, j.invalid_reason or '关联分析已失效', time.time())
        return None
    keys = set(retraction_service.registry(db))
    if retraction_service.job_matches(j, keys, db.get(Dataset, j.dataset_id)):
        return None
    if report.voided_at is not None:
        return None
    out = io.StringIO()
    out.write('﻿')
    table = j.result.get('table', {})
    cols = table.get('columns', [])
    writer = csv.writer(out)
    def safe(v):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return v
        text = str(v)
        return "'" + text if text.startswith(('=', '+', '-', '@', '\t', '\r')) else text
    writer.writerow([safe(c['label']) for c in cols])
    for row in table.get('rows', []):
        writer.writerow([safe(row.get(c['key'], '')) for c in cols])
    data = out.getvalue().encode('utf-8')
    delivery = Delivery(report_id=report.id, created_at=time.time(),
                        checksum=hashlib.sha256(data).hexdigest(), filename='', destination=report.destination)
    db.add(delivery); db.flush()
    delivery.filename = f'report-{report.id}-delivery-{delivery.id}.csv'
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    with open(os.path.join(ARTIFACT_DIR, delivery.filename), 'wb') as f:
        f.write(data)
    with open(os.path.join(ARTIFACT_DIR, delivery.filename + '.json'), 'w') as f:
        json.dump({'job': j.name, 'params': j.params, 'result': j.result, 'checksum': delivery.checksum},
                  f, ensure_ascii=False, allow_nan=False)
    report.next_run = time.time() + report.interval_seconds
    return delivery
