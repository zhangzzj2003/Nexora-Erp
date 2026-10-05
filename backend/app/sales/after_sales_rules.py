"""售后来源、数量占用、客户物品保管、工时及收费证据，共用调用方 ORM 会话。"""

import json
from decimal import Decimal
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select

from app.core.models import (AfterSalesCase, AfterSalesChange, AfterSalesCustody, AfterSalesLabor,
    AfterSalesResponsibility,
    ShipmentLine, Shipment, ShipmentReversal, SalesOrderLine, SalesOrder, Customer, Material,
    SalesReturn, SalesReturnReversal, WarehouseOutbound, WarehouseOutboundReversal, User)
from app.core.orm import model_data


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def source(db, line_id, *, writable=False):
    line = db.get(ShipmentLine, line_id)
    if line is None:
        raise HTTPException(422, '原出库明细不存在')
    shipment = db.get(Shipment, line.shipment_id)
    order_line = db.get(SalesOrderLine, line.sales_order_line_id)
    order = db.get(SalesOrder, shipment.sales_order_id)
    customer, material = db.get(Customer, order.customer_id), db.get(Material, order_line.material_id)
    valid = shipment.status == 'posted' and db.scalar(select(ShipmentReversal.id)
        .where(ShipmentReversal.shipment_id == shipment.id)) is None
    if writable and not valid:
        raise HTTPException(409, '售后须关联未冲销的已确认出库')
    return dict(shipment_line_id=line.id, shipment_id=shipment.id, sales_order_id=order.id,
        customer_id=customer.id, customer_name=customer.name, material_id=material.id,
        sku=material.sku, material_name=material.name, unit=material.unit,
        quantity=line.quantity, unit_price=order_line.unit_price, posted_at=shipment.posted_at,
        warranty_days=order_line.warranty_days, warranty_basis=order_line.warranty_basis,
        shipment_reference=shipment.reference, valid=valid)


def return_effective(db, record):
    returned = db.get(SalesReturn, record.sales_return_id) if record.sales_return_id else None
    return returned is not None and returned.status == 'posted' and db.scalar(
        select(SalesReturnReversal.id).where(SalesReturnReversal.sales_return_id == returned.id)) is None


def reserved_quantity(db, line_id, *, exclude_id=0):
    total = Decimal(0)
    for row in db.scalars(select(AfterSalesCase).where(AfterSalesCase.shipment_line_id == line_id,
        AfterSalesCase.id != exclude_id, AfterSalesCase.status.in_(
            ('submitted','approved','processing','received','repaired')))):
        # 已确认退货由原退货数量统计，不能把同一售后重复扣两次。
        if not return_effective(db, row):
            total += Decimal(row.quantity)
    return total


def remaining_quantity(db, line_id, *, exclude_id=0):
    from app.sales.returns import returned_quantity
    current = source(db, line_id)
    return Decimal(current['quantity']) - returned_quantity(db, line_id) - reserved_quantity(db, line_id, exclude_id=exclude_id)


def check_quantity(db, row):
    source(db, row.shipment_line_id, writable=True)
    if Decimal(row.quantity) > remaining_quantity(db, row.shipment_line_id, exclude_id=row.id or 0):
        raise HTTPException(409, '数量超过原出库未退回且未被其他售后占用的数量，请刷新证据')


def ensure_return_available(db, return_id, lines):
    linked = db.scalar(select(AfterSalesCase).where(AfterSalesCase.sales_return_id == return_id))
    if linked is not None and linked.status != 'processing':
        raise HTTPException(409, '关联售后未处于办理阶段，不能确认退货')
    for line in lines:
        if Decimal(line['quantity']) > remaining_quantity(db, line['shipment_line_id'], exclude_id=linked.id if linked else 0):
            raise HTTPException(409, '原出库数量被其他售后占用，不能重复退回')


def ensure_shipment_reversible(db, shipment_id):
    ids = list(db.scalars(select(ShipmentLine.id).where(ShipmentLine.shipment_id == shipment_id)))
    if db.scalar(select(AfterSalesCase.id).where(AfterSalesCase.shipment_line_id.in_(ids),
        AfterSalesCase.status.in_(('submitted','approved','processing','received','repaired','closed')))):
        raise HTTPException(409, '原出库存在有效售后，须先完成对应更正')


def ensure_replacement_available(db, order_id):
    row = db.scalar(select(AfterSalesCase).where(AfterSalesCase.replacement_order_id == order_id))
    if row is not None and (row.status not in ('processing','closed') or not return_effective(db, row)):
        raise HTTPException(409, '换货订单须在关联退货有效确认后继续，售后更正后不得继续出库')


def ensure_return_reversible(db, return_id):
    row = db.scalar(select(AfterSalesCase).where(AfterSalesCase.sales_return_id == return_id))
    if row is not None and row.replacement_order_id:
        from app.sales.orders import sales_order_data
        order = sales_order_data(db,row.replacement_order_id)
        if any(Decimal(line['net_delivered_quantity']) > 0 for line in order['lines']):
            raise HTTPException(409,'已交付换货依赖此退货，须先更正换货出库')


def authors(db, row):
    ids = set(db.scalars(select(AfterSalesChange.changed_by).where(AfterSalesChange.case_id == row.id,
        AfterSalesChange.action.in_(('create','edit','submit')))))
    return ids | {row.created_by, row.submitted_by}


def audit(db, row, action, before, user_id, reason, evidence=''):
    db.flush()
    db.add(AfterSalesChange(case_id=row.id, action=action, before_json=encoded(before) if before else None,
        after_json=encoded(model_data(row)), reason=reason, evidence=evidence, changed_by=user_id))
    db.flush()


def labor_data(db, row, cutoff=None):
    query = select(AfterSalesLabor).where(AfterSalesLabor.case_id == row.id)
    if cutoff is not None:
        query = query.where(AfterSalesLabor.created_at < cutoff)
    entries = [{**model_data(item), 'created_by_name': db.get(User, item.created_by).username}
        for item in db.scalars(query.order_by(AfterSalesLabor.id))]
    total = sum((Decimal(item['hours']) * (1 if item['action'] == 'record' else -1)
        for item in entries), Decimal(0))
    return entries, str(total.quantize(Decimal('0.01')))


def responsibility_data(db, row, cutoff=None):
    query = select(AfterSalesResponsibility).where(AfterSalesResponsibility.case_id == row.id)
    if cutoff is not None:
        query = query.where(AfterSalesResponsibility.created_at < cutoff)
    return [{**model_data(item), 'assessed_by_name': db.get(User, item.assessed_by).username}
        for item in db.scalars(query.order_by(AfterSalesResponsibility.id))]


def warranty_data(warranty_days, created_at, frozen_source):
    # 申请日固定为建单 UTC 日期，修订保修依据也不能悄悄移动申请时间。
    applied_on = date.fromisoformat(created_at[:10])
    if warranty_days is None:
        return dict(warranty_applied_on=applied_on.isoformat(), warranty_expires_on=None,
            warranty_status='unknown')
    shipped_on = date.fromisoformat(frozen_source['posted_at'][:10])
    expires_on = shipped_on + timedelta(days=warranty_days)
    status = 'unknown' if applied_on < shipped_on else (
        'within_period' if applied_on <= expires_on else 'expired')
    return dict(warranty_applied_on=applied_on.isoformat(),
        warranty_expires_on=expires_on.isoformat(), warranty_status=status)


def case_data(db, row):
    result = model_data(row)
    result['frozen_source'] = json.loads(result.pop('source_json'))
    result.update(warranty_data(row.warranty_days, row.created_at, result['frozen_source']))
    result['parts'] = json.loads(result.pop('parts_json'))
    result['current_source_valid'] = source(db, row.shipment_line_id)['valid']
    result['remaining_quantity'] = str(remaining_quantity(db, row.shipment_line_id, exclude_id=row.id))
    result['author_ids'] = sorted(identifier for identifier in authors(db, row) if identifier is not None)
    result['created_by_name'] = db.get(User, row.created_by).username
    result['custody'] = [{**model_data(item), 'created_by_name':db.get(User, item.created_by).username}
        for item in db.scalars(select(AfterSalesCustody).where(AfterSalesCustody.case_id == row.id)
            .order_by(AfterSalesCustody.id))]
    result['custody_quantity'] = str(sum((Decimal(item['quantity']) * (1 if item['action']=='receive' else -1)
        for item in result['custody']), Decimal(0)))
    result['labor'], result['labor_hours'] = labor_data(db, row)
    result['responsibilities'] = responsibility_data(db, row)
    result['responsibility'] = result['responsibilities'][-1] if result['responsibilities'] else None
    result['changes'] = [dict(id=item.id, action=item.action, reason=item.reason, evidence=item.evidence,
        changed_by=item.changed_by, changed_by_name=db.get(User, item.changed_by).username, created_at=item.created_at,
        before=json.loads(item.before_json) if item.before_json else None, after=json.loads(item.after_json))
        for item in db.scalars(select(AfterSalesChange).where(AfterSalesChange.case_id == row.id).order_by(AfterSalesChange.id))]
    result['return_effective'] = return_effective(db, row)
    if row.parts_outbound_id:
        outbound = db.get(WarehouseOutbound, row.parts_outbound_id)
        result['parts_status'] = 'reversed' if db.scalar(select(WarehouseOutboundReversal.id)
            .where(WarehouseOutboundReversal.outbound_id == outbound.id)) else outbound.status
    else:
        result['parts_status'] = None
    return result


def archive_cases(db, end_date):
    """结账固定截至期末的方案、保管和工时记录，不混入期末后的更正。"""
    cutoff = end_date + ' 24:00:00'
    result = []
    for row in db.scalars(select(AfterSalesCase).where(AfterSalesCase.created_at < cutoff)
            .order_by(AfterSalesCase.id)):
        changes = list(db.scalars(select(AfterSalesChange).where(AfterSalesChange.case_id == row.id,
            AfterSalesChange.created_at < cutoff).order_by(AfterSalesChange.id)))
        if not changes:
            continue
        header = json.loads(changes[-1].after_json)
        original = json.loads(header['source_json'])
        header.setdefault('warranty_days', None)
        header.setdefault('warranty_basis', '')
        header.update(warranty_data(header['warranty_days'], header['created_at'], original))
        custody = [{**model_data(item), 'created_by_name': db.get(User, item.created_by).username}
            for item in db.scalars(select(AfterSalesCustody).where(AfterSalesCustody.case_id == row.id,
                AfterSalesCustody.created_at < cutoff).order_by(AfterSalesCustody.id))]
        labor, labor_hours = labor_data(db, row, cutoff)
        responsibilities = responsibility_data(db, row, cutoff)
        result.append(dict(case=header, source=original,
            custody=custody, custody_quantity=str(sum((Decimal(item['quantity']) *
                (1 if item['action'] == 'receive' else -1) for item in custody), Decimal(0))),
            labor=labor, labor_hours=labor_hours,
            responsibilities=responsibilities,
            responsibility=responsibilities[-1] if responsibilities else None,
            changes=[dict(id=item.id, action=item.action, reason=item.reason, evidence=item.evidence,
                changed_by=item.changed_by, changed_by_name=db.get(User, item.changed_by).username,
                created_at=item.created_at, before=json.loads(item.before_json) if item.before_json else None,
                after=json.loads(item.after_json)) for item in changes]))
    return result


def repair_financial_entries(db):
    result = []
    for row in db.scalars(select(AfterSalesCase).where(AfterSalesCase.kind == 'repair',
        AfterSalesCase.closed_at.is_not(None), AfterSalesCase.charge_mode == 'charge')):
        original = json.loads(row.source_json)
        for reversal in (False, True):
            if reversal and row.reversed_at is None:
                continue
            kind = 'after_sales_repair_reversal' if reversal else 'after_sales_repair'
            result.append(dict(key=f'{kind}:{row.id}', kind='receivable', party_id=original['customer_id'],
                party_name=original['customer_name'], source_type=kind, source_id=row.id, source_line_id=row.id,
                order_id=original['sales_order_id'], material_id=original['material_id'], sku=original['sku'],
                quantity=row.quantity, unit_price=None, amount=str(Decimal(row.fee_amount) * (-1 if reversal else 1)),
                currency='CNY', posted_by=row.reversed_by if reversal else row.closed_by,
                posted_at=row.reversed_at if reversal else row.closed_at))
    return result
