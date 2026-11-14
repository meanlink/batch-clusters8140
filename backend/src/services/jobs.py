import time
from fastapi import HTTPException
from redis import Redis
from src.config.settings import REDIS_URL
from src.models import Dataset, Job
from src.services.business import metadata
from src.services import retractions as retraction_service
def create(db, data, user):
    dataset=db.get(Dataset,data.dataset_id)
    if not dataset: raise HTTPException(404,'数据批次不存在')
    # The registry lock makes this check and the insert atomic with respect to
    # a concurrent retraction: either the retraction is visible here, or this
    # new job becomes visible to that retraction's impact pass.
    retraction_service.registry_lock(db)
    # A retraction can land after the dataset was imported. Exclude those
    # batches from every analysis and record the exclusion on the job so the
    # result is reproducible and the omission is visible at review time.
    excluded=retraction_service.dataset_matches(dataset,set(retraction_service.registry(db)))
    allowed={p['key']:p for p in metadata().get('parameters',[])}
    if set(data.params)-set(allowed): raise HTTPException(422,'包含未知分析参数')
    params={k:p['default'] for k,p in allowed.items()}
    params.update(data.params)
    for key,p in allowed.items():
        v=params[key]
        if p['type']=='number':
            try:
                v=float(v)
                if not (p.get('min',-1e9)<=v<=p.get('max',1e9)): raise ValueError()
                params[key]=v
            except (ValueError,TypeError): raise HTTPException(422, f'{p["label"]} 超出范围或非数值')
        elif str(v) not in [str(o['value']) for o in p.get('options',[])]:
            raise HTTPException(422,f'{p["label"]} 不是有效选项')
    j=Job(name=data.name, dataset_id=data.dataset_id, params=params, created_by=user.id, created_at=time.time(), status='queued', excluded_batch_ids=excluded or None)
    db.add(j); db.flush()
    return j
def enqueue(job_id):
    try:
        r=Redis.from_url(REDIS_URL); r.rpush('analysis:queue',job_id); r.close()
    except Exception:
        pass # SQL queued status is the durable fallback
