"""维护工单的备件采购来源与后续到货证据。"""

from app.core.document_responses import NumberedRoute
import json
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from app.access.security import require
from app.core.models import (
    MaintenanceJob, MaintenancePurchaseRequest, PurchaseGoodsReceipt,
    PurchaseGoodsReceiptLine, PurchaseOrder, PurchaseOrderLine,
    PurchaseOrderRequestLink, PurchaseRequest, PurchaseRequestLine, Receipt,
)
from app.core.orm import add_model, model_data, orm_session
from app.production.equipment_inputs import Part
from app.production.equipment_rules import audit, get, job_data, permission, version
from app.purchase.requests import PurchaseRequestInput, create_purchase_request_in_session

router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/equipment')


class MaintenancePurchaseInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    version: int = Field(gt=0, strict=True)
    reason: str = Field(min_length=1, max_length=200)
    evidence: str = Field(min_length=1, max_length=600)
    parts: list[Part] = Field(min_length=1, max_length=100)

    @field_validator('parts')
    @classmethod
    def unique_parts(cls, value):
        if len({part.material_id for part in value}) != len(value):
            raise ValueError('采购备件不能重复')
        return value


def requested_quantity(db, job_id: int) -> dict[int, Decimal]:
    result: dict[int, Decimal] = {}
    rows = db.execute(select(PurchaseRequestLine.material_id, PurchaseRequestLine.quantity)
        .join(MaintenancePurchaseRequest,
              MaintenancePurchaseRequest.purchase_request_id == PurchaseRequestLine.purchase_request_id)
        .join(PurchaseRequest, PurchaseRequest.id == MaintenancePurchaseRequest.purchase_request_id)
        .where(MaintenancePurchaseRequest.job_id == job_id, PurchaseRequest.status != 'cancelled'))
    for material_id, quantity in rows:
        result[material_id] = result.get(material_id, Decimal(0)) + Decimal(quantity)
    return result


def procurement_data(db, job_id: int) -> list[dict]:
    requests = []
    links = db.scalars(select(MaintenancePurchaseRequest)
        .where(MaintenancePurchaseRequest.job_id == job_id)
        .order_by(MaintenancePurchaseRequest.id))
    for link in links:
        request = db.get(PurchaseRequest, link.purchase_request_id)
        lines = []
        for line in db.scalars(select(PurchaseRequestLine)
                .where(PurchaseRequestLine.purchase_request_id == request.id)
                .order_by(PurchaseRequestLine.id)):
            orders = []
            order_links = db.execute(select(PurchaseOrderLine, PurchaseOrder)
                .join(PurchaseOrderRequestLink,
                      PurchaseOrderRequestLink.purchase_order_line_id == PurchaseOrderLine.id)
                .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
                .where(PurchaseOrderRequestLink.purchase_request_line_id == line.id)
                .order_by(PurchaseOrderLine.id))
            for order_line, order in order_links:
                receipts = []
                receipt_rows = db.execute(select(PurchaseGoodsReceiptLine, PurchaseGoodsReceipt)
                    .join(PurchaseGoodsReceipt,
                          PurchaseGoodsReceipt.id == PurchaseGoodsReceiptLine.goods_receipt_id)
                    .where(PurchaseGoodsReceiptLine.purchase_order_line_id == order_line.id)
                    .order_by(PurchaseGoodsReceiptLine.id))
                for receipt_line, receipt in receipt_rows:
                    receipts.append({
                        'id': receipt.id, 'status': receipt.status,
                        'accepted_quantity': receipt_line.accepted_quantity,
                        'inbound_receipt_id': receipt.inbound_receipt_id,
                        'inbound_status': db.get(Receipt, receipt.inbound_receipt_id).status
                            if receipt.inbound_receipt_id else None,
                    })
                orders.append({'id': order.id, 'status': order.status,
                               'quantity': order_line.quantity, 'goods_receipts': receipts})
            lines.append({'material_id': line.material_id, 'quantity': line.quantity, 'orders': orders})
        requests.append({'id': request.id, 'reference': request.reference, 'status': request.status,
                         'reason': link.reason, 'evidence': link.evidence,
                         'created_by': link.created_by, 'created_at': link.created_at,
                         'lines': lines})
    return requests


@router.post('/jobs/{identifier}/purchase-requests', status_code=201)
def create_maintenance_purchase(identifier: int, payload: MaintenancePurchaseInput,
                                user: dict = Depends(require('purchase_request.create'))):
    permission(user, 'equipment.view')
    permission(user, 'purchase_request.view')
    with orm_session(write=True) as db:
        job = get(db, MaintenanceJob, identifier, '维护工单')
        version(job, payload.version)
        if job.status not in ('approved', 'in_progress'):
            raise HTTPException(409, '只能为已批准或执行中的维护工单申请备件采购')
        planned = {part['material_id']: Decimal(part['quantity']) for part in json.loads(job.parts_json)}
        requested = requested_quantity(db, job.id)
        for part in payload.parts:
            if part.material_id not in planned:
                raise HTTPException(422, f'物料 #{part.material_id} 不在已批准的维护耗材中')
            if requested.get(part.material_id, Decimal(0)) + part.quantity > planned[part.material_id]:
                raise HTTPException(409, f'物料 #{part.material_id} 的采购申请超过维护耗材数量')
        before = model_data(job)
        request = create_purchase_request_in_session(db, PurchaseRequestInput(
            reference=f'M-{job.id}-{job.version}',
            note=f'维护工单 {job.reference}：{payload.reason}',
            lines=[{'material_id': part.material_id, 'quantity': part.quantity} for part in payload.parts],
        ), user)
        add_model(db, MaintenancePurchaseRequest(
            job_id=job.id, purchase_request_id=request['id'], reason=payload.reason,
            evidence=payload.evidence, created_by=user['id']))
        job.version += 1
        audit(db, 'job', job, 'procure', before, user, payload.reason, payload.evidence)
        return job_data(db, job, user)
