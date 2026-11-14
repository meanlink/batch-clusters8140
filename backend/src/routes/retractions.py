from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config.database import get_db
from src.models import Retraction
from src.schemas.retraction import RetractionInput
from src.middlewares.auth import current_user, admin_only
from src.services import retractions as retraction_service
from src.services.audit import record
from src.utils.serialization import retraction_dict
router=APIRouter(prefix='/retractions')
@router.get('')
def listing(db=Depends(get_db),u=Depends(current_user)):
    return [retraction_dict(r) for r in db.scalars(select(Retraction).order_by(Retraction.id.desc()))]
@router.get('/impact')
def impact(db=Depends(get_db),u=Depends(current_user)):
    return retraction_service.impact(db)
@router.post('',status_code=201)
def create(data:RetractionInput,db=Depends(get_db),u=Depends(admin_only)):
    created,summary=retraction_service.register(db,data,u)
    record(db,u.email,'retraction.create',{'batch_ids':[r.batch_id for r in created],'reason':data.reason.strip(),'impact':summary})
    db.commit()
    return {'retractions':[retraction_dict(r) for r in created],'impact':summary}
