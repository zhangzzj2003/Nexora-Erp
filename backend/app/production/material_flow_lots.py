"""生产交接批次额度；签收、损坏隔离和退库共用不可变实物事实。"""

from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select

from app.core.models import (
    MaterialFlowExecutionLot, MaterialFlowLine, MaterialIssue, MaterialIssueLine,
    MaterialReturn, MaterialReturnLine, MaterialReturnReversal,
    PhysicalLot, PhysicalLotAllocation, PhysicalLotMovementEvidence, StockMovement,
)
from app.inventory.physical_lots import LotPart
from app.production.material_flow_rules import ZERO, active_facts, source_movement


def _add(target, lot_id, quantity):
    target[lot_id] = target.get(lot_id, ZERO) + quantity


def _movement_lots(db, movement):
    result = {}
    if movement is None:
        return result
    # 后补证也是真实实物依据，但不推断没有保存的历史批次。
    for model in (PhysicalLotAllocation, PhysicalLotMovementEvidence):
        for item in db.scalars(select(model).where(model.movement_id == movement.id)):
            _add(result, item.lot_id, -Decimal(item.quantity))
    return result


def _fact_lots(db, line_id, actions=('execute',), exclude_fact_id=None):
    result = {}
    ids = [fact.id for fact, _ in active_facts(db, line_id, actions) if fact.id != exclude_fact_id]
    if ids:
        for item in db.scalars(select(MaterialFlowExecutionLot).where(
                MaterialFlowExecutionLot.execution_line_id.in_(ids))):
            _add(result, item.lot_id, Decimal(item.quantity))
    return result


def source_lot_capacity(db, line, action='execute', exclude_fact_id=None):
    original = source_movement(db, line)
    if line.document_type == 'receipt':
        # 未签交接与签收共同消耗本次原发出批次，不能把已签收的批次按未签差额退回。
        capacity = _movement_lots(db, original)
        used = _fact_lots(db, line.id, ('execute', 'handover_return'), exclude_fact_id)
        for lot_id, quantity in used.items():
            _add(capacity, lot_id, -quantity)
        return capacity
    if line.source_receipt_line_id:
        capacity = _fact_lots(db, line.source_receipt_line_id)
        source_filter = MaterialFlowLine.source_receipt_line_id == line.source_receipt_line_id
    elif line.legacy_issue_line_id:
        old_line = db.get(MaterialIssueLine, line.legacy_issue_line_id)
        issue = db.get(MaterialIssue, old_line.material_issue_id) if old_line else None
        capacity = _movement_lots(db, original) if issue and issue.historical_direct else {}
        if issue and not issue.historical_direct:
            for receipt in db.scalars(select(MaterialFlowLine).where(
                    MaterialFlowLine.document_type == 'receipt',
                    MaterialFlowLine.legacy_issue_line_id == old_line.id)):
                for lot_id, quantity in _fact_lots(db, receipt.id).items():
                    _add(capacity, lot_id, quantity)
        # 旧入口正常退料同样占用原签收批次，保持新旧入口共同上限。
        if old_line:
            returns = db.scalars(select(MaterialReturnLine).join(MaterialReturn,
                MaterialReturn.id == MaterialReturnLine.material_return_id).where(
                MaterialReturnLine.material_issue_line_id == old_line.id,
                MaterialReturn.status == 'posted', MaterialReturn.id.not_in(
                    select(MaterialReturnReversal.material_return_id))))
            for returned in returns:
                movement = db.scalar(select(StockMovement).where(
                    StockMovement.source_type == 'material_return', StockMovement.source_line_id == returned.id))
                for lot_id, quantity in _movement_lots(db, movement).items():
                    _add(capacity, lot_id, quantity)
        source_filter = MaterialFlowLine.legacy_issue_line_id == line.legacy_issue_line_id
    else:
        return {}
    for other in db.scalars(select(MaterialFlowLine).where(
            MaterialFlowLine.document_type.in_(('return', 'exchange')), source_filter)):
        for lot_id, quantity in _fact_lots(db, other.id, exclude_fact_id=exclude_fact_id).items():
            _add(capacity, lot_id, -quantity)
    return capacity


def available_source_lots(db, line, action='execute'):
    capacity = source_lot_capacity(db, line, action)
    return [{'lot_id': lot.id, 'code': lot.code, 'quantity': str(capacity[lot.id])}
            for lot in db.scalars(select(PhysicalLot).where(PhysicalLot.id.in_(capacity)).order_by(PhysicalLot.id))
            if capacity[lot.id] > ZERO]


def source_remaining_quantity(db, line, exclude_fact_id=None):
    """计算实物来源余量，包含未知批次；不能只看已知批次推断实际交接。"""
    def actual(identifier, actions=('execute',)):
        return sum((Decimal(fact.quantity) for fact, _ in active_facts(db, identifier, actions)
                    if fact.id != exclude_fact_id), ZERO)

    if line.document_type == 'receipt':
        return Decimal(line.quantity) - actual(line.id, ('execute', 'handover_return'))
    if line.source_receipt_line_id:
        quantity = actual(line.source_receipt_line_id)
        source_filter = MaterialFlowLine.source_receipt_line_id == line.source_receipt_line_id
    elif line.legacy_issue_line_id:
        old_line = db.get(MaterialIssueLine, line.legacy_issue_line_id)
        issue = db.get(MaterialIssue, old_line.material_issue_id) if old_line else None
        if issue is None:
            return ZERO
        quantity = Decimal(old_line.quantity) if issue.historical_direct else sum((actual(receipt.id)
            for receipt in db.scalars(select(MaterialFlowLine).where(MaterialFlowLine.document_type == 'receipt',
                MaterialFlowLine.legacy_issue_line_id == old_line.id))), ZERO)
        quantity -= sum((Decimal(value) for value in db.scalars(select(MaterialReturnLine.quantity)
            .join(MaterialReturn, MaterialReturn.id == MaterialReturnLine.material_return_id)
            .where(MaterialReturnLine.material_issue_line_id == old_line.id, MaterialReturn.status == 'posted',
                MaterialReturn.id.not_in(select(MaterialReturnReversal.material_return_id))))), ZERO)
        source_filter = MaterialFlowLine.legacy_issue_line_id == old_line.id
    else:
        return ZERO
    return quantity - sum((actual(other.id) for other in db.scalars(select(MaterialFlowLine).where(
        MaterialFlowLine.document_type.in_(('return', 'exchange')), source_filter))), ZERO)


def _select_parts(capacity, quantity, selected, source_remaining):
    if selected:
        parts = [LotPart(part.lot_id, Decimal(part.quantity)) for part in selected]
        if len({part.lot_id for part in parts}) != len(parts) or sum((part.quantity for part in parts), ZERO) != quantity:
            raise HTTPException(422, '批次数量之和必须等于本次交接数量')
        if any(part.quantity <= ZERO or part.quantity > capacity.get(part.lot_id, ZERO) for part in parts):
            raise HTTPException(409, '所选批次超过本来源已签收或待签收的可用数量')
        return parts
    available = {lot_id: value for lot_id, value in capacity.items() if value > ZERO}
    known_quantity = sum(available.values(), ZERO)
    # 旧退料未登记批次时，候选批次合计可能大于来源余量；即使退完余额也没有足够证据自动归批。
    if known_quantity > source_remaining or (available and quantity < source_remaining
            and (len(available) > 1 or known_quantity < source_remaining)):
        raise HTTPException(422, '来源批次无法唯一确定，请选择本次实际交接批次')
    remaining, parts = quantity, []
    # 全量交接可直接沿用全部已知批次；部分交接不能猜测少收的是哪个批次。
    for lot_id in sorted(capacity):
        amount = min(remaining, max(ZERO, capacity[lot_id]))
        if amount:
            parts.append(LotPart(lot_id, amount))
            remaining -= amount
        if remaining == ZERO:
            break
    return parts


def return_lots(db, line, quantity, selected, action='execute'):
    parts = _select_parts(source_lot_capacity(db, line, action), quantity, selected,
                          source_remaining_quantity(db, line))
    # 公共库存批次写入要求全量守恒；历史来源不完整时走普通入库并保留批次差额。
    return parts if sum((part.quantity for part in parts), ZERO) == quantity else []


def record_execution_lots(db, line, fact, action, selected_lots, movement=None):
    if fact.reverses_line_id is not None:
        return
    if line.document_type == 'dispatch':
        parts = [LotPart(item.lot_id, abs(Decimal(item.quantity))) for item in db.scalars(
            select(PhysicalLotAllocation).where(PhysicalLotAllocation.movement_id == movement.id))] if movement else []
    else:
        # 执行行已首次插入，计算额度时排除自身，随后批次事实与库存一并提交。
        parts = _select_parts(source_lot_capacity(db, line, action, fact.id), Decimal(fact.quantity), selected_lots,
                              source_remaining_quantity(db, line, fact.id))
    db.add_all(MaterialFlowExecutionLot(execution_line_id=fact.id, lot_id=part.lot_id,
        quantity=str(part.quantity)) for part in parts)
    db.flush()
