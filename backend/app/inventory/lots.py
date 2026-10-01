"""在同一库存写事务追加系统批次分配，金额与财务移动平均成本保持独立。"""
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import select
from app.core.models import StockMovement, InventoryLot, MovementLot, SalesReturnLine, MaterialReturnLine, ProductionCompletionReversal
from app.core.orm import add_model


def balance(db,lot,warehouse):
    opening=Decimal(lot.legacy_quantity) if lot.legacy_warehouse_id==warehouse else Decimal(0)
    return opening+sum((Decimal(q) for q in db.scalars(select(MovementLot.quantity).join(StockMovement,StockMovement.id==MovementLot.movement_id)
        .where(MovementLot.lot_id==lot.id,StockMovement.warehouse_id==warehouse))),Decimal(0))


def source_movement(db,row):
    kind=line=None
    if row.source_type in ('transfer_in','transfer_reversal_in'):
        kind=row.source_type.replace('_in','_out');line=row.source_line_id
    elif row.source_type=='sales_return':
        value=db.get(SalesReturnLine,row.source_line_id);kind='shipment';line=value.shipment_line_id if value else None
    elif row.source_type=='material_return':
        value=db.get(MaterialReturnLine,row.source_line_id);kind='material_issue';line=value.material_issue_line_id if value else None
    elif row.source_type=='production_completion_reversal':
        value=db.get(ProductionCompletionReversal,row.source_line_id)
        kind='production_completion';line=value.production_completion_id if value else None
    elif row.source_type.endswith('_reversal'):
        kind=row.source_type.removesuffix('_reversal');line=row.source_line_id
    if kind and line:
        return db.scalar(select(StockMovement).where(StockMovement.source_type==kind,StockMovement.source_line_id==line,
            StockMovement.material_id==row.material_id).order_by(StockMovement.id))
    return None


def record_movements(db,head):
    rows=list(db.scalars(select(StockMovement).where(StockMovement.id>head).order_by(StockMovement.id)))
    for row in rows:
        if db.scalar(select(MovementLot.movement_id).where(MovementLot.movement_id==row.id)):continue
        quantity=Decimal(row.quantity)
        if not quantity:continue
        source=source_movement(db,row)
        if quantity>0:
            original=list(db.scalars(select(MovementLot).where(MovementLot.movement_id==source.id))) if source else []
            remaining=quantity
            returned={}
            # 分次退回按原出库各批次的未退数量分配，已冲销的退回也计入净额。
            if source and row.source_type in ('sales_return','material_return'):
                for prior in db.scalars(select(StockMovement).where(StockMovement.id<row.id,StockMovement.material_id==row.material_id,
                        StockMovement.source_type.in_((row.source_type,row.source_type+'_reversal')))):
                    origin=source_movement(db,prior)
                    if prior.source_type.endswith('_reversal') and origin:origin=source_movement(db,origin)
                    if origin is None or origin.id!=source.id:continue
                    for item in db.scalars(select(MovementLot).where(MovementLot.movement_id==prior.id)):
                        returned[item.lot_id]=returned.get(item.lot_id,Decimal(0))+Decimal(item.quantity)
            for allocation in original:
                part=min(remaining,max(abs(Decimal(allocation.quantity))-returned.get(allocation.lot_id,Decimal(0)),Decimal(0)))
                if part>0:db.add(MovementLot(movement_id=row.id,lot_id=allocation.lot_id,quantity=str(part)));remaining-=part
            if remaining:
                lot=add_model(db,InventoryLot(code=f'LOT-{row.id}',material_id=row.material_id,origin_movement_id=row.id,basis='系统入库批次'))
                db.add(MovementLot(movement_id=row.id,lot_id=lot.id,quantity=str(remaining)))
        else:
            lots=list(db.scalars(select(InventoryLot).where(InventoryLot.material_id==row.material_id).order_by(InventoryLot.id)))
            # 历史存量没有批次记录时只建一份有明确标记的期初余额，不能虚构物理批号。
            legacy=next((lot for lot in lots if lot.legacy_warehouse_id==row.warehouse_id),None)
            if legacy is None:
                opening=sum((Decimal(q) for q in db.scalars(select(StockMovement.quantity).where(StockMovement.id<=head,
                    StockMovement.material_id==row.material_id,StockMovement.warehouse_id==row.warehouse_id,
                    ~StockMovement.id.in_(select(MovementLot.movement_id))))),Decimal(0))
                legacy=add_model(db,InventoryLot(code=f'LEGACY-{row.warehouse_id}-{row.material_id}',material_id=row.material_id,
                    legacy_warehouse_id=row.warehouse_id,legacy_quantity=str(max(opening,Decimal(0))),basis='历史存量，批次待补录'))
                lots.append(legacy)
            if source and Decimal(source.quantity)>0:
                origin_ids=set(db.scalars(select(MovementLot.lot_id).where(MovementLot.movement_id==source.id)))
                # 系统 FIFO 不代表物理批号；优先冲回原批次，再按当前可用库存分配。
                # 不能因推断的批次已被调拨而拒绝现有按总库存校验的冲销业务。
                lots.sort(key=lambda lot:(lot.id not in origin_ids,lot.id))
            remaining=-quantity
            for lot in lots:
                available=balance(db,lot,row.warehouse_id)
                part=min(remaining,max(available,Decimal(0)))
                if part>0:db.add(MovementLot(movement_id=row.id,lot_id=lot.id,quantity=str(-part)));remaining-=part
                if remaining==0:break
            if remaining>0:raise HTTPException(409,'系统批次可用数量不足，请核对库存及冲销记录')
        # 让下一条调拨入库能读取刚追加的出库批次，仍受外层事务整体回滚保护。
        db.flush()
