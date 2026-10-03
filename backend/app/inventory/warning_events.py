"""服务端定时核对库存预警状态，并保留异常进入与恶化的证据。"""

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.access.security import require
from app.core.models import InventoryWarningEvent, InventoryWarningObservation, InventoryWarningRule, Warehouse
from app.core.orm import orm_session, model_data
from app.inventory.warnings import balances, current_row

router = APIRouter(prefix='/api/v1/inventory/warnings')
logger = logging.getLogger(__name__)
ATTENTION = frozenset(('low', 'out_of_stock'))


def scan_warning_events() -> int:
    """先在读快照计算数量，再短暂持有写锁固定状态与事件。"""
    created = 0
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')
    with orm_session() as db:
        quantities = balances(db)
        rows = [current_row(db, rule, quantities.get((rule.warehouse_id, rule.material_id), Decimal(0)))
                for rule in db.scalars(select(InventoryWarningRule).order_by(InventoryWarningRule.id))]
    with orm_session(write=True) as db:
        for row in rows:
            rule = db.get(InventoryWarningRule, row['id'])
            # 规则在读写两段之间被修订时，下轮再以新规则核对，避免旧阈值写入事件。
            if rule is None or rule.version != row['version']:
                continue
            observation = db.get(InventoryWarningObservation, rule.id)
            if observation is not None and observation.observed_at >= stamp:
                continue
            previous = observation.status if observation else None
            status = row['status']
            if status in ATTENTION and (previous not in ATTENTION or
                                        previous == 'low' and status == 'out_of_stock'):
                db.add(InventoryWarningEvent(rule_id=rule.id, warehouse_id=rule.warehouse_id,
                    material_id=rule.material_id, previous_status=previous, status=status,
                    quantity=row['quantity'], threshold=row['threshold'], shortage=row['shortage'],
                    rule_version=rule.version, warehouse_code=row['warehouse_code'],
                    warehouse_name=row['warehouse_name'], sku=row['sku'],
                    material_name=row['material_name'], unit=row['unit'], observed_at=stamp))
                created += 1
            if observation is None:
                db.add(InventoryWarningObservation(rule_id=rule.id, status=status,
                                                   quantity=row['quantity'], observed_at=stamp))
            else:
                observation.status = status
                observation.quantity = row['quantity']
                observation.observed_at = stamp
    return created


async def run_warning_event_scheduler() -> None:
    # 首轮先核对已有异常；读取或锁库失败后仍继续下一轮，不让后台任务静默退出。
    while True:
        worker = asyncio.create_task(asyncio.to_thread(scan_warning_events))
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError:
            # 关闭服务时等待正在写入的线程结束，避免后台线程越过生命周期边界。
            try:
                await worker
            except Exception:
                logger.exception('库存预警事件核对在关闭期间失败')
            raise
        except Exception:
            logger.exception('库存预警事件核对失败')
        await asyncio.sleep(60)


@router.get('/events')
def list_warning_events(
    warehouse_id: Annotated[int | None, Query(gt=0)] = None,
    before_id: Annotated[int | None, Query(gt=0)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    _: dict = Depends(require('inventory.view')),
) -> dict:
    with orm_session() as db:
        if warehouse_id is not None and db.get(Warehouse, warehouse_id) is None:
            raise HTTPException(404, '仓库不存在')
        statement = select(InventoryWarningEvent).order_by(InventoryWarningEvent.id.desc()).limit(limit + 1)
        if warehouse_id is not None:
            statement = statement.where(InventoryWarningEvent.warehouse_id == warehouse_id)
        if before_id is not None:
            statement = statement.where(InventoryWarningEvent.id < before_id)
        rows = db.scalars(statement).all()
        events = [model_data(row) for row in rows[:limit]]
        return {'as_of': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                'warehouse_id': warehouse_id, 'events': events,
                'next_before_id': events[-1]['id'] if len(rows) > limit else None}
