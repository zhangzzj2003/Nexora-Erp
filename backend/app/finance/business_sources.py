"""业务凭证金额来源；服务端重放原单据，不接受客户端分录金额。"""

import hashlib
import json
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import (PaymentRecord, ProductionCostEntry, ProductionCostReversal, Material, Warehouse,
    SubledgerPayment, SubledgerOpeningLine, QualityDisposition, QualityCostAllocation,
    ProductionSettlementReversal)
from app.core.orm import model_data
from app.finance.routes import financial_entries
from app.inventory.valuation import calculate_valuation

ROLE_LABELS = {
    'inventory': '库存', 'payable': '应付', 'receivable': '应收', 'income': '销售收入',
    'sales_cost': '销售成本', 'cash': '收付款资金', 'price_variance': '采购价差',
    'work_in_progress': '生产在制成本', 'labor_accrual': '人工费用对方',
    'overhead_accrual': '制造费用对方', 'inventory_offset': '其他库存变动对方',
    'quality_loss': '不合格品独立报废损失',
    'repair_income': '售后维修服务收入',
}
SOURCE_LABELS = {
    'receipt': '采购入库', 'receipt_reversal': '采购入库冲销',
    'purchase_return': '采购退货', 'purchase_return_reversal': '采购退货冲销',
    'shipment': '销售出库', 'shipment_reversal': '销售出库冲销',
    'sales_return': '销售退货', 'sales_return_reversal': '销售退货冲销',
    'other_inbound': '其他入库', 'other_inbound_reversal': '其他入库冲销',
    'other_outbound': '其他出库', 'other_outbound_reversal': '其他出库冲销',
    'stocktake': '盘点差异', 'stocktake_reversal': '盘点冲销',
    'adjustment': '库存调整', 'adjustment_reversal': '库存调整冲销',
    'material_issue': '生产领料', 'material_issue_reversal': '生产领料冲销',
    'material_return': '生产退料', 'material_return_reversal': '生产退料冲销',
    'production_completion': '生产完工', 'production_completion_reversal': '生产完工冲销',
    'production_charge': '生产费用', 'production_charge_reversal': '生产费用冲销',
    'payment_record': '收付款登记',
    'subledger_payment': '分户期初收付款',
    'quality_loss': '不合格品报废损失',
    'after_sales_repair': '售后维修服务费', 'after_sales_repair_reversal': '售后维修服务费更正',
}


def encoded(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def business_sources(db: Session) -> dict[str, dict]:
    groups = {}
    labels = {f'material:{item.id}': f'{item.sku} · {item.name}' for item in db.scalars(select(Material))}
    labels.update({f'warehouse:{item.id}': f'{item.code} · {item.name}' for item in db.scalars(select(Warehouse))})

    def group(kind, identifier, timestamp):
        key = f'{kind}:{identifier}'
        if key not in groups:
            groups[key] = dict(key=key, source_type=kind, source_id=identifier,
                label=SOURCE_LABELS.get(kind, kind), source_date=timestamp[:10],
                movements=[], business=[], records=[], roles={}, blockers=[], warnings=[], labels={})
        return groups[key]

    for movement in calculate_valuation(db).report['movements']:
        kind = movement['source_type']
        # 公司内部调拨不改变总账库存；仓库维度继续从库存台账核对。
        if kind.startswith('transfer_'):
            continue
        item = group(kind, movement['source_id'], movement['created_at'])
        item['movements'].append({key: movement[key] for key in (
            'id', 'warehouse_id', 'material_id', 'quantity', 'source_line_id', 'created_at',
            'amount', 'accounting_amount', 'unit_cost', 'cost_source', 'cost_input_id', 'settlement_id')})
    for entry in financial_entries(db):
        item = group(entry['source_type'], entry['source_id'], entry['posted_at'])
        item['business'].append({key: entry[key] for key in (
            'source_line_id', 'order_id', 'party_id', 'material_id', 'quantity', 'unit_price',
            'amount', 'kind', 'posted_at')})
    for record in db.scalars(select(PaymentRecord).order_by(PaymentRecord.id)):
        item = group('payment_record', record.id, record.created_at)
        item['records'].append(model_data(record))
    for record in db.scalars(select(SubledgerPayment).order_by(SubledgerPayment.id)):
        line = db.get(SubledgerOpeningLine, record.opening_line_id)
        item = group('subledger_payment', record.id, record.created_at)
        item['records'].append(dict(**model_data(record), kind=line.kind,
            party_id=line.customer_id or line.supplier_id, account_id=line.account_id,
            document_reference=line.document_reference, auxiliary=json.loads(line.auxiliary_json)))
    charges = {record.id: record for record in db.scalars(select(ProductionCostEntry)
        .where(ProductionCostEntry.kind.in_(('labor', 'overhead'))))}
    for record in charges.values():
        group('production_charge', record.id, record.created_at)['records'].append(model_data(record))
    for reversal in db.scalars(select(ProductionCostReversal).order_by(ProductionCostReversal.id)):
        if reversal.entry_id in charges:
            item = group('production_charge_reversal', reversal.id, reversal.created_at)
            item['records'].extend((model_data(reversal), model_data(charges[reversal.entry_id])))
    for disposition in db.scalars(select(QualityDisposition).where(QualityDisposition.status == 'posted',
        QualityDisposition.loss_treatment == 'expense').order_by(QualityDisposition.id)):
        allocation = db.scalar(select(QualityCostAllocation).where(
            QualityCostAllocation.disposition_id == disposition.id,
            ~select(ProductionSettlementReversal.id).where(
                ProductionSettlementReversal.settlement_id == QualityCostAllocation.settlement_id).exists()))
        item = group('quality_loss', disposition.id, disposition.posted_at)
        item['records'].append({key: getattr(disposition, key) for key in (
            'id','completion_id','reference','quantity','defect','action_note','posted_by','posted_at')})
        item['records'].append(model_data(allocation) if allocation else None)
        if allocation is None:
            item['blockers'].append('原工单尚未结算独立报废成本，不能按零生成损失凭证')

    for item in groups.values():
        roles = {}

        def add(role, value):
            roles[role] = roles.get(role, Decimal(0)) + value

        kind = item['source_type']
        inventory = Decimal(0)
        for movement in item['movements']:
            if movement['accounting_amount'] is None:
                item['blockers'].append(f"库存流水 #{movement['id']} 未核价")
            else:
                inventory += Decimal(movement['accounting_amount'])
        if item['movements']:
            add('inventory', inventory)
        trade = Decimal(0)
        for entry in item['business']:
            if entry['amount'] is None:
                item['blockers'].append('往来来源没有单价，库存核价不能替代订单价格')
            else:
                trade += Decimal(entry['amount'])
        if item['business']:
            if kind.startswith('after_sales_repair'):
                # 服务费来自已检验交还的维修单，不虚构公司商品出库。
                add('receivable', trade)
                add('repair_income', -trade)
            elif not item['movements']:
                item['blockers'].append('往来来源缺少对应库存流水，不能仅按订单金额生成')
            if kind.startswith('after_sales_repair'):
                pass
            elif kind.startswith(('shipment', 'sales_return')):
                add('receivable', trade)
                add('income', -trade)
                add('sales_cost', -inventory)
            else:
                add('payable', -trade)
                add('price_variance', trade - inventory)
        elif item['movements']:
            if kind.startswith(('material_', 'production_completion')):
                add('work_in_progress', -inventory)
            elif kind in SOURCE_LABELS:
                add('inventory_offset', -inventory)
            else:
                item['blockers'].append('此库存来源尚无凭证规则')
        if kind in ('payment_record', 'subledger_payment'):
            record = item['records'][0]
            value = Decimal(record['amount'])
            if record['kind'] == 'receivable':
                add('cash', value)
                add('receivable', -value)
            else:
                add('payable', value)
                add('cash', -value)
            item['warnings'].append('资金来源为人工登记；生成凭证不证明银行实际到账')
        if kind.startswith('production_charge'):
            record = item['records'][-1]
            value = Decimal(record['amount']) * (-1 if kind.endswith('_reversal') else 1)
            add('work_in_progress', value)
            add(record['kind'] + '_accrual', -value)
        if kind == 'quality_loss' and item['records'][-1] is not None:
            value = Decimal(item['records'][-1]['amount'])
            add('quality_loss', value)
            add('work_in_progress', -value)
        item['roles'] = {key: f'{value:.2f}' for key, value in roles.items() if value}
        if sum(roles.values(), Decimal(0)):
            item['blockers'].append('来源借贷不平衡，请核对库存与业务资料')
        if any(abs(value) >= Decimal('1000000000000') for value in roles.values()):
            item['blockers'].append('来源金额超过凭证金额上限')
        economic = {key: item[key] for key in ('key', 'source_date', 'movements', 'business', 'records', 'roles')}
        item['fingerprint'] = hashlib.sha256(encoded(economic).encode()).hexdigest()
        for movement in item['movements']:
            for field, prefix in (('material_id', 'material'), ('warehouse_id', 'warehouse')):
                key = f'{prefix}:{movement[field]}'
                item['labels'][key] = labels.get(key, key)
    return groups
