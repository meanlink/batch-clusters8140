from fastapi import HTTPException
from sqlalchemy import select
from src.models import Dataset
from src.services.business import metadata
from src.services import retractions as retraction_service
from src.utils.serialization import checksum
import math, time
def normalize_records(db, records):
    """Validate/normalize rows and flag retracted batch numbers on the snapshot."""
    for index,row in enumerate(records):
        for c in metadata()['columns']:
            value=row.get(c['key'])
            if value is None or value=='': raise HTTPException(422, f'第 {index+1} 行缺少字段 {c["label"]}')
            if c['type']=='number':
                try:
                    if isinstance(value,bool) or not math.isfinite(float(value)): raise ValueError()
                    row[c['key']]=float(value)
                except (TypeError, ValueError, OverflowError): raise HTTPException(422, f'第 {index+1} 行 {c["label"]} 必须为有限数值')
    return retraction_service.rows_matches(records,set(retraction_service.registry(db)))
def create(db, data):
    name=data.name.strip()
    if len(name)<2: raise HTTPException(422, '批次名称去除空格后至少需要两个字符')
    # Hold the registry lock while importing so a retraction committed just
    # before this import can never be missed by the quarantine check.
    retraction_service.registry_lock(db)
    if db.scalar(select(Dataset).where(Dataset.name==name)):
        raise HTTPException(409, '该数据批次名已存在，请修改名称')
    matched=normalize_records(db,data.records)
    d=Dataset(name=name, source=data.source, records=data.records, checksum=checksum(data.records),
              created_at=time.time(), retracted_batch_ids=matched)
    db.add(d); db.flush()
    return d
