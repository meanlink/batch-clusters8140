from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config.database import get_db
from src.models import Dataset, Job
from src.schemas.job import JobInput
from src.middlewares.auth import current_user, can_write, admin_only
from src.services import jobs
from src.services import retractions as retraction_service
from src.services.audit import record
from src.utils.serialization import job_dict
router=APIRouter(prefix='/jobs')
@router.get('')
def listing(db=Depends(get_db),u=Depends(current_user)):
    return [job_dict(j) for j in db.scalars(select(Job).order_by(Job.id.desc()).limit(100))]
@router.post('',status_code=201)
def create(data:JobInput,db=Depends(get_db),u=Depends(can_write)):
    j=jobs.create(db,data,u); record(db,u.email,'job.create',{'id':j.id,'params':j.params})
    db.commit(); jobs.enqueue(j.id); return job_dict(j)
@router.get('/{id}')
def detail(id:int,db=Depends(get_db),u=Depends(current_user)):
    j=db.get(Job,id)
    if not j: raise HTTPException(404,'分析任务不存在')
    return job_dict(j)
@router.post('/{id}/approve')
def approve(id:int,db=Depends(get_db),u=Depends(admin_only)):
    # Approval and retraction are serialized: a retraction that commits first
    # makes this job invalid and unapprovable; one that commits after will
    # revoke this approval in its own impact pass.
    retraction_service.registry_lock(db)
    j=db.get(Job,id)
    if not j: raise HTTPException(404,'分析任务不存在')
    if j.status=='invalid' or j.invalidated_at:
        raise HTTPException(409,'该分析含已撤回批次，不能批准')
    if j.status!='completed': raise HTTPException(409,'仅已完成结果可以批准')
    if retraction_service.job_matches(j,set(retraction_service.registry(db)),db.get(Dataset,j.dataset_id)):
        raise HTTPException(409,'该分析含已撤回批次，不能批准')
    j.approved=True; record(db,u.email,'job.approve',{'id':id}); db.commit()
    return job_dict(j)
@router.post('/{id}/recompute',status_code=201)
def recompute(id:int,db=Depends(get_db),u=Depends(can_write)):
    j=db.get(Job,id)
    if not j: raise HTTPException(404,'分析任务不存在')
    new_job=retraction_service.recompute(db,j,u)
    record(db,u.email,'job.recompute',{'id':new_job.id,'replaces':j.id,'excluded':new_job.excluded_batch_ids})
    db.commit(); jobs.enqueue(new_job.id); return job_dict(new_job)
@router.get('/{id}/impact')
def impact(id:int,db=Depends(get_db),u=Depends(current_user)):
    j=db.get(Job,id)
    if not j: raise HTTPException(404,'分析任务不存在')
    data=retraction_service.impact(db)
    data['job']=job_dict(j)
    affected=retraction_service.job_matches(j,set(retraction_service.registry(db)),db.get(Dataset,j.dataset_id))
    data['affected_batches']=affected
    data['job_impact']={
        'reports':[r for r in data['reports'] if r['job_id']==j.id],
        'deliveries':[d for d in data['deliveries'] if any(r['id']==d['report_id'] and r['job_id']==j.id for r in data['reports'])],
    }
    return data
