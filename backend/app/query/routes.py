"""先在数据库完成权限、搜索、排序与分页，再序列化当前页单据。"""
from dataclasses import dataclass
from decimal import Decimal
import json
from typing import Callable
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, func, or_, cast, String
from sqlalchemy.orm import Session
from app.access.security import current_user, require, user_details
from app.access.routes import role_details
from app.core import models as m
from app.core.orm import orm_session, model_data
from app.sales.customers import customer_data, customer_access
from app.sales.customer_scope import is_admin, protect_amount
from app.sales.orders import sales_order_data, shipment_data
from app.sales.returns import public_return
from app.purchase.orders import order_data
from app.purchase.requests import request_data
from app.purchase.goods_receipts import goods_receipt_data
from app.purchase.receipts import receipt_data
from app.purchase.returns import purchase_return_data
from app.inventory.inbounds import inbound_data
from app.inventory.outbounds import outbound_data
from app.inventory.adjustments import adjustment_data
from app.inventory.stocktake import stocktake_data
from app.inventory.warehouse import transfer_data
from app.inventory.stock import MOVEMENT_LINKS
from app.production.boms import bom_data
from app.production.work_orders import work_order_data
from app.production.material_issues import material_issue_data
from app.production.material_returns import material_return_data
from app.production.completions import completion_data
from app.production.settlements import settlement_data
from app.finance.journals import view as journal_view
from app.finance.opening_balances import view as opening_view
from app.finance.routes import payment_data

router = APIRouter(prefix='/api/v1/tables')


class TableQuery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    dataset: str = Field(min_length=1, max_length=60)
    query: str = Field(default='', max_length=120)
    page: int = Field(default=1, ge=1, le=2147483647)
    page_size: int = Field(default=20, ge=1, le=100)
    sort: str = Field(default='', max_length=60)
    descending: bool = True
    snapshot_id: str = Field(default='', max_length=100)
    snapshot_path: str = Field(default='rows', max_length=100)
    filters: dict[str, str | int | bool | None] = Field(default_factory=dict)


@dataclass(frozen=True)
class TableSpec:
    model: type
    permission: str
    serializer: Callable | None = None
    parent: str | None = None


# 可查询资源由服务端白名单声明，绝不接受任意表名、SQL、字段表达式或函数路径。
SPECS = {
    'boundMaterials': TableSpec(m.Material, 'inventory.view'),
    'periodClosingHistory': TableSpec(m.PeriodClosing, 'accounting_period.closing_view', parent='period_id'),
    'materials': TableSpec(m.Material, 'inventory.view'),
    'suppliers': TableSpec(m.Supplier, 'inventory.view'),
    'supplierMaterials': TableSpec(m.SupplierMaterial, 'inventory.view', parent='supplier_id'),
    'customers': TableSpec(m.Customer, 'customer.view', customer_data),
    'warehouses': TableSpec(m.Warehouse, 'inventory.view'),
    'users': TableSpec(m.User, 'users.manage', user_details),
    'roles': TableSpec(m.Role, 'users.manage', role_details),
    'purchaseRequests': TableSpec(m.PurchaseRequest, 'purchase_request.view', request_data),
    'purchaseOrders': TableSpec(m.PurchaseOrder, 'inventory.view', order_data),
    'goodsReceipts': TableSpec(m.PurchaseGoodsReceipt, 'purchase_receiving.view', goods_receipt_data),
    'receipts': TableSpec(m.Receipt, 'inventory.view', receipt_data),
    'purchaseReturns': TableSpec(m.PurchaseReturn, 'inventory.view', purchase_return_data),
    'otherInbounds': TableSpec(m.WarehouseInbound, 'other_inbound.view', inbound_data),
    'warehouseOutbounds': TableSpec(m.WarehouseOutbound, 'other_outbound.view', outbound_data),
    'stockAdjustments': TableSpec(m.StockAdjustment, 'adjustment.view', adjustment_data),
    'transfers': TableSpec(m.Transfer, 'inventory.view', transfer_data),
    'stocktakes': TableSpec(m.Stocktake, 'inventory.view', stocktake_data),
    'salesOrders': TableSpec(m.SalesOrder, 'sales.view', lambda db,key,user: protect_amount(db,sales_order_data(db,key),user,key)),
    'shipments': TableSpec(m.Shipment, 'sales.view', shipment_data),
    'salesReturns': TableSpec(m.SalesReturn, 'sales.view', public_return),
    'boms': TableSpec(m.Bom, 'production.view', bom_data),
    'workOrders': TableSpec(m.WorkOrder, 'production.view', work_order_data),
    'materialIssues': TableSpec(m.MaterialIssue, 'production.view', material_issue_data),
    'materialReturns': TableSpec(m.MaterialReturn, 'production.view', material_return_data),
    'productionCompletions': TableSpec(m.ProductionCompletion, 'production.view', completion_data),
    'productionCostSettlements': TableSpec(m.ProductionCostSettlement, 'production_cost.view', settlement_data),
    'ledgerAccounts': TableSpec(m.LedgerAccount, 'ledger_account.view'),
    'accountingPeriods': TableSpec(m.AccountingPeriod, 'accounting_period.view'),
    'journals': TableSpec(m.Journal, 'journal.view', lambda db,key: journal_view(db,db.get(m.Journal,key))),
    'openingBalances': TableSpec(m.OpeningBalance, 'opening_balance.view', lambda db,key: opening_view(db,db.get(m.OpeningBalance,key))),
    'paymentRecords': TableSpec(m.PaymentRecord, 'finance.view', payment_data),
    'inventoryCostInputs': TableSpec(m.InventoryCostInput, 'inventory_valuation.view'),
    'customerHistory': TableSpec(m.CustomerChange, 'customer.view', parent='customer_id'),
    'journalHistory': TableSpec(m.JournalChange, 'journal.view', parent='journal_id'),
    'openingHistory': TableSpec(m.OpeningBalanceChange, 'opening_balance.view', parent='opening_balance_id'),
    'ledgerAccountHistory': TableSpec(m.LedgerAccountChange, 'ledger_account.view', parent='account_id'),
    'periodHistory': TableSpec(m.AccountingPeriodChange, 'accounting_period.view', parent='period_id'),
    'movements': TableSpec(m.StockMovement, 'inventory.view'),
    'journalLines': TableSpec(m.JournalLine, 'journal.view', parent='journal_id'),
    'openingLines': TableSpec(m.OpeningBalanceLine, 'opening_balance.view', parent='opening_balance_id'),
    'stock': TableSpec(m.Material, 'inventory.view'),
}


def search_condition(model, text: str):
    # 字面子串搜索不用 LIKE 通配符；只搜索公开标识、名称和业务字段。
    expressions=[]
    allowed={'id','code','sku','name','username','full_name','employee_no','phone','reference','status','note','reason'}
    for column in model.__table__.columns:
        if column.key in allowed:
            expressions.append(func.instr(func.lower(cast(column,String)),text.lower()) > 0)
    for column in model.__table__.columns:
        for foreign in column.foreign_keys:
            target=foreign.column.table.name
            related={'customers':m.Customer,'suppliers':m.Supplier,'materials':m.Material,'warehouses':m.Warehouse,'users':m.User}.get(target)
            if related is not None:
                labels=[getattr(related,key) for key in ('name','sku','username','full_name') if hasattr(related,key)]
                expressions.append(select(related).where(getattr(related,foreign.column.key)==column,
                    or_(*(func.instr(func.lower(cast(label,String)),text.lower()) > 0 for label in labels))).exists())
    # 主单通过关联明细搜索物料，不把全部明细拉入 Python 再过滤。
    for child in m.Base.registry.mappers:
        table=child.local_table
        parents=[column for column in table.columns if any(fk.column.table.name==model.__tablename__ for fk in column.foreign_keys)]
        if parents and 'material_id' in table.c and hasattr(model,'id'):
            material=table.c.material_id
            expressions.append(select(table).join(m.Material,m.Material.id==material).where(parents[0]==model.id,
                or_(func.instr(func.lower(m.Material.name),text.lower())>0,func.instr(func.lower(m.Material.sku),text.lower())>0)).exists())
    return or_(*expressions)


def serialize(db: Session, spec: TableSpec, key, user: dict, dataset: str) -> dict:
    if spec.serializer:
        return spec.serializer(db,key,user) if dataset in ('salesOrders','salesReturns') else spec.serializer(db,key)
    row=db.get(spec.model,key)
    if dataset=='periodClosingHistory':
        return {field:getattr(row,field) for field in ('id','period_id','period_version','action','reason','created_by','created_at')} | {'evidence':{},'created_by_name':db.get(m.User,row.created_by).username}
    if dataset=='customerHistory' and not is_admin(user):
        return {field:getattr(row,field) for field in ('id','action','reason','changed_by','created_at')}
    result=model_data(row)
    if dataset.endswith('History'):
        result['before']=json.loads(result.pop('before_json')) if result.get('before_json') else None
        result['after']=json.loads(result.pop('after_json')) if result.get('after_json') else None
        result['changed_by_name']=db.get(m.User,row.changed_by).username

    if hasattr(row,'created_by'):
        creator=db.get(m.User,row.created_by)
        result['created_by_name']=creator.username if creator else ''
    if dataset=='stock':
        stmt=select(m.StockMovement.quantity).where(m.StockMovement.material_id==key)
        # 库存计算在调用方处理筛选；数量保持 Decimal 精度。
        result['quantity']=str(sum((Decimal(q) for q in db.scalars(stmt)),Decimal(0)))
    if dataset=='movements':
        result.update(warehouse_name=db.get(m.Warehouse,row.warehouse_id).name,
            sku=db.get(m.Material,row.material_id).sku,material_name=db.get(m.Material,row.material_id).name,
            unit=db.get(m.Material,row.material_id).unit,
            **{name:row.source_id if row.source_type in kinds else None for name,kinds in MOVEMENT_LINKS.items()})
    return result


def page_items(items: list[dict], payload: TableQuery, metadata: dict | None = None) -> dict:
    # 派生金额、期初和累计余额先按完整范围计算，再分页返回结果，不能按单页重算。
    if payload.query.strip():
        text=payload.query.strip().casefold()
        items=[row for row in items if any(text in str(value).casefold() for key,value in row.items() if not key.endswith('_json') and not isinstance(value,(dict,list)))]
    if payload.filters:
        items=[row for row in items if all(value is None or str(row.get(key))==str(value) for key,value in payload.filters.items())]
    total=len(items)
    page=min(payload.page,max(1,(total+payload.page_size-1)//payload.page_size))
    return {'items':items[(page-1)*payload.page_size:page*payload.page_size],'total':total,'page':page,'page_size':payload.page_size,'metadata':metadata}


COMPUTED={
    'inventoryValuationMaterials':('inventory_valuation.view','valuation','materials'),
    'inventoryValuationMovements':('inventory_valuation.view','valuation','movements'),
    'productionCostOrders':('production_cost.view','cost','orders'),
    'productionCostEntries':('production_cost.view','cost','entries'),
    'productionMaterialSources':('production_cost.view','cost','material_sources'),
    'financeAccounts':('finance.view','finance','accounts'),
    'financialSources':('finance.view','finance','entries'),
}


@router.post('/snapshot-csv')
def export_snapshot(payload: dict[str,str], user: dict = Depends(current_user)) -> dict:
    from app.query.snapshots import read_snapshot
    result=read_snapshot(payload.get('snapshot_id',''),user)
    return {'csv':result.get('csv','')}


@router.post('/query')
def query_table(payload: TableQuery, user: dict = Depends(current_user)) -> dict:
    if payload.dataset=='closingEvidence':
        require('accounting_period.closing_view')(user)
        record_id=payload.filters.get('id')
        with orm_session() as db:
            record=db.get(m.PeriodClosing,record_id) if isinstance(record_id,int) else None
            if record is None: raise HTTPException(404,'结账证据不存在')
            from app.query.snapshots import snapshot_metadata
            result={field:getattr(record,field) for field in ('id','period_id','period_version','action','reason','created_by','created_at')}
            result.update(evidence=json.loads(record.snapshot_json),created_by_name=db.get(m.User,record.created_by).username)
            paths=('evidence.ledger.rows','evidence.inventory.materials','evidence.inventory.movements','evidence.business_sources.entries','evidence.payments')
            return {'items':[snapshot_metadata(result,user,paths)],'total':1,'page':1,'page_size':1}
    if payload.dataset=='snapshot':
        from app.query.snapshots import read_snapshot
        result=read_snapshot(payload.snapshot_id,user)
        target=result
        # 只能读取快照中已授权的数组；不执行表达式或反射 Python 对象。
        for key in payload.snapshot_path.split('.'):
            target=target.get(key) if isinstance(target,dict) else None
        if not isinstance(target,list) or any(not isinstance(row,dict) for row in target):
            raise HTTPException(422,'不支持的快照表格')
        return page_items(target,payload)
    if payload.dataset in COMPUTED:
        permission,kind,field=COMPUTED[payload.dataset]
        require(permission)(user)
        with orm_session() as db:
            if kind=='valuation':
                from app.inventory.valuation import valuation_report
                report=valuation_report(db)
            elif kind=='cost':
                from app.production.costs import cost_report
                report=cost_report(db)
            else:
                from app.finance.routes import financial_entries,report_data,account_data
                entries=financial_entries(db)
                keys={(row['kind'],row['order_id']) for row in entries if row['order_id'] is not None}
                report={**report_data(entries),'accounts':[account_data(db,kind,key,entries) for kind,key in sorted(keys)]}
            metadata={key:value for key,value in report.items() if not isinstance(value,list)}
            if kind=='valuation': metadata['unpriced_movement_ids']=report['unpriced_movement_ids']
            return page_items(report[field],payload,metadata)
    spec=SPECS.get(payload.dataset)
    if spec is None:
        raise HTTPException(422,'不支持的表格查询')
    if payload.dataset in ('customers','customerHistory'):
        customer_access(user)
    else:
        require(spec.permission)(user)
    if len(payload.filters)>12:
        raise HTTPException(422,'筛选条件过多')
    with orm_session() as db:
        model=spec.model
        primary=list(model.__table__.primary_key.columns)
        stmt=select(*primary)
        if payload.dataset=='boundMaterials':
            supplier_id=payload.filters.get('supplier_id')
            if not isinstance(supplier_id,int) or supplier_id<=0: raise HTTPException(422,'须指定供应商')
            stmt=stmt.join(m.SupplierMaterial,m.SupplierMaterial.material_id==m.Material.id).where(m.SupplierMaterial.supplier_id==supplier_id)
        if payload.dataset=='customers':
            stmt=stmt.join(m.CustomerProfile,m.CustomerProfile.customer_id==m.Customer.id)
            if not is_admin(user):
                stmt=stmt.where(m.CustomerProfile.owner_id==user['id'])
        if spec.parent:
            parent_id=payload.filters.get(spec.parent)
            if not isinstance(parent_id,int) or isinstance(parent_id,bool) or parent_id<=0:
                raise HTTPException(422,'须指定所属记录')
            if payload.dataset=='customerHistory':
                from app.sales.customer_scope import require_customer
                require_customer(db,parent_id,user)
                if not is_admin(user): stmt=stmt.where(m.CustomerChange.order_id.is_(None))
        for name,value in payload.filters.items():
            if value is None: continue
            if name=='warehouse_id' and payload.dataset=='stock': continue
            if name=='supplier_id' and payload.dataset=='boundMaterials': continue
            if name not in model.__table__.columns or name not in {'id','warehouse_id','material_id','customer_id','supplier_id','status','is_active','customer_id','journal_id','opening_balance_id','account_id','period_id','work_order_id','owner_id','code','source_type'}:
                raise HTTPException(422,'不支持的筛选字段')
            stmt=stmt.where(getattr(model,name)==value)
        if payload.query.strip():
            predicate=search_condition(model,payload.query.strip())
            if payload.dataset=='customers':
                text=payload.query.strip().lower()
                private_fields=[m.CustomerProfile.contact_name,m.CustomerProfile.phone,m.CustomerProfile.address]
                predicate=or_(predicate,*(func.instr(func.lower(column),text)>0 for column in private_fields),
                    select(m.User).where(m.User.id==m.CustomerProfile.owner_id,
                        or_(func.instr(func.lower(m.User.username),text)>0,func.instr(func.lower(m.User.full_name),text)>0)).exists())
            stmt=stmt.where(predicate)
        total=db.scalar(select(func.count()).select_from(stmt.subquery()))
        page=min(payload.page,max(1,(total+payload.page_size-1)//payload.page_size))
        sorting=payload.sort or primary[0].key
        if sorting not in {column.key for column in primary}|{'code','sku','name','created_at','status'} or sorting not in model.__table__.columns:
            raise HTTPException(422,'不支持的排序字段')
        order=getattr(model,sorting)
        ordering=[order.desc() if payload.descending else order.asc()]
        ordering.extend(column.desc() for column in primary if column.key!=sorting)
        keys=db.execute(stmt.order_by(*ordering).limit(payload.page_size).offset((page-1)*payload.page_size)).all()
        items=[serialize(db,spec,key[0] if len(primary)==1 else tuple(key),user,payload.dataset) for key in keys]
        if payload.dataset=='stock' and payload.filters.get('warehouse_id'):
            for item in items:
                quantities=db.scalars(select(m.StockMovement.quantity).where(m.StockMovement.material_id==item['id'],m.StockMovement.warehouse_id==payload.filters['warehouse_id']))
                item['quantity']=str(sum((Decimal(q) for q in quantities),Decimal(0)))
        metadata=None
        if payload.dataset=='stock':
            metadata={'material_count':db.scalar(select(func.count()).select_from(m.Material)),
                'posted_receipt_count':db.scalar(select(func.count()).select_from(m.Receipt).where(m.Receipt.status=='posted')),
                'movement_count':db.scalar(select(func.count()).select_from(m.StockMovement))}
        return {'items':items,'total':total,'page':page,'page_size':payload.page_size,'metadata':metadata}
