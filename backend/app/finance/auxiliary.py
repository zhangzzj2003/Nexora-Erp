"""辅助维度快照随凭证保存，重命名不会改写已过账历史。"""
import json
from fastapi import HTTPException
from app.core.models import JournalAuxiliary, Customer, Supplier
from app.core.orm import model_data


def save_auxiliary(db, line_id, value):
    labels={}
    for key, model in (('customer_id',Customer),('supplier_id',Supplier)):
        identifier=getattr(value,key)
        row=db.get(model,identifier) if identifier else None
        if identifier and row is None: raise HTTPException(422,'辅助核算往来单位不存在')
        if row: labels[key]=row.name
    db.add(JournalAuxiliary(line_id=line_id,customer_id=value.customer_id,supplier_id=value.supplier_id,
        department=value.department.strip(),project=value.project.strip(),labels_json=json.dumps(labels,ensure_ascii=False)))


def auxiliary_data(db, line_id):
    row=db.get(JournalAuxiliary,line_id)
    if row is None:return {}
    data=model_data(row);data.pop('line_id');data['labels']=json.loads(data.pop('labels_json'));return data


def copy_auxiliary(db, source_id, target_id):
    row=db.get(JournalAuxiliary,source_id)
    if row:
        data=model_data(row);data['line_id']=target_id;db.add(JournalAuxiliary(**data))
