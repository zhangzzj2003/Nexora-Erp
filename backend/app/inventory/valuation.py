"""按物料汇总的移动加权平均库存计价及可追溯人工核价。"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access.security import require
from app.core.period_lock import ensure_movement_unlocked
from app.core.orm import orm_session, model_data
from app.core.models import (StockMovement, Material, InventoryCostInput, ReceiptOrderLink,
    PurchaseOrderLine, SalesReturnLine, MaterialReturnLine, User,
    ProductionCostAllocation, ProductionSettlementDependency, ProductionSettlementReversal)

router = APIRouter(prefix="/api/v1/inventory/valuation")
CENT = Decimal("0.01")
FOUR_PLACES = Decimal("0.0001")
MANUAL_SOURCES = {"receipt", "other_inbound", "stocktake", "adjustment",
                  "production_completion"}
PAIRED_SOURCES = {
    "transfer_in": "transfer_out",
    "transfer_reversal_in": "transfer_reversal_out",
    "shipment_reversal": "shipment",
    "other_outbound_reversal": "other_outbound",
    "purchase_return_reversal": "purchase_return",
    "stocktake_reversal": "stocktake",
    "adjustment_reversal": "adjustment",
    "material_issue_reversal": "material_issue",
    "material_return_reversal": "material_return",
}


def money(value: Decimal) -> str:
    return str(value.quantize(CENT, rounding=ROUND_HALF_UP))


def unit_price(value: Decimal) -> str:
    return str(value.quantize(FOUR_PLACES, rounding=ROUND_HALF_UP))


class CostInput(BaseModel):
    movement_id: int = Field(gt=0)
    unit_cost: Decimal
    reference: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("unit_cost")
    @classmethod
    def valid_cost(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < 0 or value > 1_000_000_000 or value.as_tuple().exponent < -4:
            raise ValueError("核定单价须非负、最多四位小数且不超过十亿")
        return value

    @field_validator("reference", "reason")
    @classmethod
    def trim_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("核价依据和原因不能为空")
        return value.strip()


def purchase_prices(session: Session) -> dict[int, Decimal]:
    return {movement_id: Decimal(price) for movement_id, price in session.execute(
        select(StockMovement.id, PurchaseOrderLine.unit_price)
        .join(ReceiptOrderLink, ReceiptOrderLink.receipt_line_id == StockMovement.source_line_id)
        .join(PurchaseOrderLine, PurchaseOrderLine.id == ReceiptOrderLink.purchase_order_line_id)
        .where(StockMovement.source_type == 'receipt'))}


def linked_source_lines(session: Session) -> dict[tuple[str, int], tuple[str, int]]:
    links = {}
    for row in session.scalars(select(SalesReturnLine)):
        links[("sales_return", row.id)] = ("shipment", row.shipment_line_id)
    for row in session.scalars(select(MaterialReturnLine)):
        links[("material_return", row.id)] = ("material_issue", row.material_issue_line_id)
    return links


@dataclass
class ValuationResult:
    report: dict
    movement_costs: dict[int, Decimal | None]
    dependencies: dict[int, set[tuple[str, int]]]


def calculate_valuation(session: Session, *, through_date: str | None = None) -> ValuationResult:
    """按流水 ID 重放；后登记的核价会重算未结期间的历史金额。"""
    rates = {}
    for row in session.scalars(select(InventoryCostInput).order_by(InventoryCostInput.id)):
        rates[row.movement_id] = (Decimal(row.unit_cost), row.id)
    order_prices = purchase_prices(session)
    linked = linked_source_lines(session)
    allocations = {row.movement_id: model_data(row) for row in session.scalars(select(ProductionCostAllocation).where(
        ~select(ProductionSettlementReversal.id).where(
            ProductionSettlementReversal.settlement_id == ProductionCostAllocation.settlement_id).exists()))}
    settlement_dependencies: dict[int, set[tuple[str, int]]] = {}
    for row in session.scalars(select(ProductionSettlementDependency)):
        settlement_dependencies.setdefault(row.settlement_id, set()).add((row.kind, row.source_id))
    quantities: dict[int, Decimal] = {}
    values: dict[int, Decimal | None] = {}
    source_costs: dict[tuple[str, int], Decimal | None] = {}
    source_dependencies: dict[tuple[str, int], set[tuple[str, int]]] = {}
    inventory_dependencies: dict[int, set[tuple[str, int]]] = {}
    movement_costs: dict[int, Decimal | None] = {}
    dependencies: dict[int, set[tuple[str, int]]] = {}
    movements = []
    unpriced = []
    statement = select(StockMovement).order_by(StockMovement.id)
    if through_date is not None:
        statement = statement.where(StockMovement.created_at < through_date + ' 24:00:00')
    for movement in session.scalars(statement):
        row = model_data(movement)
        material_id = row["material_id"]
        quantity = Decimal(row["quantity"])
        before_quantity = quantities.get(material_id, Decimal(0))
        before_value = values.get(material_id, Decimal(0))
        unit_cost: Decimal | None
        cost_source = "moving_average"
        allocation = allocations.get(row['id'])
        movement_dependencies = set(inventory_dependencies.get(material_id, set()))
        if quantity > 0:
            paired = linked.get((row["source_type"], row["source_line_id"]))
            if paired is None and row["source_type"] in PAIRED_SOURCES:
                paired = (PAIRED_SOURCES[row["source_type"]], row["source_line_id"])
            if allocation is not None:
                unit_cost = Decimal(allocation['amount']) / quantity
                cost_source = 'production_settlement'
                movement_dependencies = {('settlement', allocation['settlement_id'])}
                movement_dependencies.update(settlement_dependencies.get(allocation['settlement_id'], set()))
            elif row["id"] in order_prices:
                unit_cost = order_prices[row["id"]]
                cost_source = "purchase_order"
                movement_dependencies = set()
            elif row["id"] in rates:
                unit_cost = rates[row["id"]][0]
                cost_source = "manual"
                movement_dependencies = {('input', row['id'])}
            elif paired is not None:
                unit_cost = source_costs.get(paired)
                cost_source = "linked_movement" if unit_cost is not None else "unpriced"
                movement_dependencies = set(source_dependencies.get(paired, set()))
            else:
                unit_cost = None
                cost_source = "unpriced"
                # 未核价来源也须留依赖，防止人工领料成本结算后补价改变原始成本链。
                movement_dependencies = {('input', row['id'])} if row['source_type'] in MANUAL_SOURCES else set()
            if unit_cost is None:
                unpriced.append(row["id"])
        else:
            if row['source_type'] == 'material_return_reversal':
                paired = ('material_return', row['source_line_id'])
                unit_cost = source_costs.get(paired)
                cost_source = 'linked_movement' if unit_cost is not None else 'unpriced'
                movement_dependencies = set(source_dependencies.get(paired, set()))
            else:
                unit_cost = (before_value / before_quantity
                             if before_quantity > 0 and before_value is not None else None)
                if unit_cost is None:
                    cost_source = "unpriced"
        # 分摊额以分为最小单位；内部单价保持精度，不能由四位展示单价倒算金额。
        amount = (Decimal(allocation['amount']) if allocation is not None
                  else quantity * unit_cost if unit_cost is not None else None)
        after_quantity = before_quantity + quantity
        if after_quantity == 0:
            # 全部出清后，新入库不继承旧期间未知成本或舍入尾差。
            after_value: Decimal | None = Decimal(0)
        elif before_value is None or amount is None:
            after_value = None
        else:
            after_value = before_value + amount
        quantities[material_id] = after_quantity
        values[material_id] = after_value
        dependencies[row['id']] = movement_dependencies
        movement_costs[row['id']] = unit_cost
        inventory_dependencies[material_id] = (set() if after_quantity == 0 else
            inventory_dependencies.get(material_id, set()) | movement_dependencies)
        source_costs[(row["source_type"], row["source_line_id"])] = unit_cost
        source_dependencies[(row['source_type'], row['source_line_id'])] = movement_dependencies
        movements.append({**dict(row), "unit_cost": unit_price(unit_cost) if unit_cost is not None else None,
                          "amount": money(amount) if amount is not None else None,
                          # 总账按前后余额的分位差入账，出清时同时结清累计舍入尾差。
                          "accounting_amount": (money(Decimal(money(after_value)) - Decimal(money(before_value)))
                                                if before_value is not None and after_value is not None and amount is not None else None),
                          "cost_source": cost_source,
                          "cost_input_id": rates[row["id"]][1] if row["id"] in rates and allocation is None else None,
                          "settlement_id": allocation['settlement_id'] if allocation is not None else None})
    materials = []
    for material in session.scalars(select(Material).order_by(Material.sku)):
        row = {key: getattr(material, key) for key in ('id', 'sku', 'name', 'unit')}
        quantity = quantities.get(row["id"], Decimal(0))
        amount = values.get(row["id"], Decimal(0))
        materials.append({**dict(row), "quantity": str(quantity),
                          "amount": money(amount) if amount is not None else None,
                          "average_unit_cost": unit_price(amount / quantity)
                          if amount is not None and quantity > 0 else None})
    total = (None if any(item["amount"] is None for item in materials)
             else money(sum((Decimal(item["amount"]) for item in materials), Decimal(0))))
    report = {"currency": "CNY", "method": "moving_weighted_average",
            "scope": "company", "total_amount": total, "materials": materials,
            "movements": movements, "unpriced_movement_ids": unpriced}
    return ValuationResult(report, movement_costs, dependencies)


def valuation_report(session: Session) -> dict:
    return calculate_valuation(session).report


@router.get("")
def get_valuation(_: dict = Depends(require("inventory_valuation.view"))) -> dict:
    with orm_session() as session:
        return valuation_report(session)


@router.get("/inputs")
def list_cost_inputs(_: dict = Depends(require("inventory_valuation.view"))) -> list[dict]:
    with orm_session() as session:
        return [{**model_data(row), 'created_by_name': username} for row, username in session.execute(
            select(InventoryCostInput, User.username).join(User, User.id == InventoryCostInput.created_by)
            .order_by(InventoryCostInput.id.desc()))]


@router.post("/inputs", status_code=201)
def record_cost(payload: CostInput,
                user: dict = Depends(require("inventory_valuation.record"))) -> dict:
    with orm_session(write=True) as session:
        movement = session.get(StockMovement, payload.movement_id)
        if not movement:
            raise HTTPException(404, "库存流水不存在")
        ensure_movement_unlocked(session, movement.id)
        if Decimal(movement.quantity) <= 0 or movement.source_type not in MANUAL_SOURCES:
            raise HTTPException(409, "此流水的成本须沿用原单据或移动平均，不可人工核价")
        if payload.movement_id in purchase_prices(session):
            raise HTTPException(409, "采购订单已有单价，不能覆盖原始价格")
        dependency = session.scalar(select(ProductionSettlementDependency.settlement_id).where(
            ProductionSettlementDependency.kind == 'input', ProductionSettlementDependency.source_id == payload.movement_id,
            ~select(ProductionSettlementReversal.id).where(ProductionSettlementReversal.settlement_id == ProductionSettlementDependency.settlement_id).exists()).limit(1))
        allocation = session.scalar(select(ProductionCostAllocation.settlement_id).where(
            ProductionCostAllocation.movement_id == payload.movement_id,
            ~select(ProductionSettlementReversal.id).where(ProductionSettlementReversal.settlement_id == ProductionCostAllocation.settlement_id).exists()).limit(1))
        if dependency is not None or allocation is not None:
            raise HTTPException(409, "此成本来源已用于完工成本结算，须先冲销相关结算再核价")
        if session.scalar(select(InventoryCostInput.id).where(
            InventoryCostInput.movement_id == payload.movement_id, InventoryCostInput.reference == payload.reference).limit(1)) is not None:
            raise HTTPException(409, "同一流水不能重复使用核价依据编号")
        row = InventoryCostInput(movement_id=payload.movement_id, unit_cost=str(payload.unit_cost),
            reference=payload.reference, reason=payload.reason, created_by=user['id'])
        session.add(row)
        session.flush()
        return {**model_data(row), 'created_by_name': session.get(User, user['id']).username}
