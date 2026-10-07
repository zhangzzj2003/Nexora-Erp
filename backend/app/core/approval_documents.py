"""审批领域适配器；明细快照和可执行状态必须由服务端业务模型生成。"""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import WarehouseInbound, WarehouseInboundLine, WarehouseInboundReversal


def inbound_snapshot(db: Session, identifier: int) -> dict:
    source = db.get(WarehouseInbound, identifier)
    if source is None:
        raise HTTPException(404, '其他入库单不存在')
    # 不纳入流程时间、展示编号或基础资料名称；核对的是入库业务内容本身。
    return {'warehouse_id': source.warehouse_id, 'reason': source.reason,
            'note': source.note, 'reference': source.reference,
            'lines': [{'id': line.id, 'material_id': line.material_id, 'quantity': line.quantity}
                      for line in db.scalars(select(WarehouseInboundLine).where(
                          WarehouseInboundLine.inbound_id == identifier).order_by(WarehouseInboundLine.id))]}


def inbound_pending(db: Session, identifier: int, intent: str) -> WarehouseInbound:
    source = db.get(WarehouseInbound, identifier)
    if source is None:
        raise HTTPException(404, '其他入库单不存在')
    # 历史已入库数据不补造审批；只有新的入库动作或尚未冲销的冲销动作可送审。
    expected = 'draft' if intent == 'execute' else 'posted'
    if source.status != expected or (intent == 'reverse' and db.scalar(select(
            WarehouseInboundReversal.id).where(WarehouseInboundReversal.inbound_id == identifier))):
        raise HTTPException(409, '此入库动作已处理，不能继续审批')
    return source


def document_snapshot(db: Session, document_type: str, identifier: int, intent: str,
                      reason: str = '') -> dict:
    if document_type != 'WarehouseInbound':
        # 逐类接入领域边界；不能在尚未接入的类型上生成看似有效的批准记录。
        raise HTTPException(409, '此类单据的统一审批入口尚未接入')
    inbound_pending(db, identifier, intent)
    content = inbound_snapshot(db, identifier)
    if intent == 'reverse':
        if not reason.strip() or len(reason.strip()) > 200:
            raise HTTPException(422, '冲销原因必填，最多二百字')
        return {'document': content, 'reversal_reason': reason.strip()}
    return content


def submit_permission(document_type: str, intent: str) -> str | None:
    # 冲销送审/撤回沿用冲销权限，不能因为有建单权限而获得冲销权限。
    if document_type == 'WarehouseInbound' and intent == 'reverse':
        return 'other_inbound.reverse'
    return None
