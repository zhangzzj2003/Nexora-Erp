"""审批类型与领域权限白名单；角色按钮权限与业务执行权限分别校验。"""

from dataclasses import dataclass

from fastapi import HTTPException

from app.core import models
from app.core.document_types import DOCUMENT_TYPES


@dataclass(frozen=True)
class ApprovalType:
    model_name: str
    title: str
    view_permission: str
    submit_permission: str
    review_permission: str
    execute_permission: str
    native_workflow: bool = False

    def step_permission(self, step: dict) -> str:
        # 步骤名称允许自定义，授权以固定动作代码为准；旧模板按名称兼容识别。
        action = approval_step_action(step)
        return self.review_permission if action == 'review' else self.review_permission.rsplit('.', 1)[0] + '.' + action

    @property
    def model(self):
        # 只取静态模型；不允许客户端提供表名或反射任意业务表。
        return getattr(models, self.model_name)


# 各领域原审核代码保持不变，核准与批准以同一前缀生成独立按钮权限。
_RULES = (
    ('PurchaseRequest', '采购申请', 'purchase_request.view', 'purchase_request.submit', 'purchase_request.review', 'purchase_order.create', True),
    ('PurchaseOrder', '采购订单', 'inventory.view', 'purchase_order.create', 'purchase_order.review', 'purchase_order.confirm', False),
    ('PurchaseGoodsReceipt', '采购收货', 'purchase_receiving.view', 'purchase_receiving.create', 'purchase_receiving.review', 'purchase_receiving.confirm', False),
    ('Receipt', '采购入库', 'inventory.view', 'receipt.create', 'receipt.review', 'receipt.post', False),
    ('PurchaseReturn', '采购退货', 'inventory.view', 'purchase_return.create', 'purchase_return.review', 'purchase_return.submit', False),
    ('WarehouseInbound', '其他入库', 'other_inbound.view', 'other_inbound.create', 'other_inbound.review', 'other_inbound.post', False),
    ('WarehouseOutbound', '仓库出库', 'other_outbound.view', 'other_outbound.create', 'other_outbound.review', 'other_outbound.post', False),
    ('Transfer', '仓库调拨', 'inventory.view', 'transfer.create', 'transfer.review', 'transfer.post', False),
    ('Stocktake', '库存盘点', 'inventory.view', 'stocktake.create', 'stocktake.review', 'stocktake.post', False),
    ('StockAdjustment', '库存调整', 'adjustment.view', 'adjustment.submit', 'adjustment.review', 'adjustment.post', True),
    ('CrmQuote', '销售报价', 'crm.view', 'crm_quote.submit', 'crm_quote.review', 'crm_quote.convert', True),
    ('SalesOrder', '销售订单', 'sales.view', 'sales_order.create', 'sales_order.review', 'sales_order.confirm', False),
    ('Shipment', '销售出库', 'sales.view', 'shipment.create', 'shipment.review', 'shipment.post', False),
    ('SalesReturn', '销售退货', 'sales.view', 'sales_return.create', 'sales_return.review', 'sales_return.post', False),
    ('AfterSalesCase', '售后单', 'after_sales.view', 'after_sales.submit', 'after_sales.review', 'after_sales.process', True),
    ('WorkOrder', '生产工单', 'production.view', 'work_order.create', 'work_order.review', 'work_order.release', False),
    ('MaterialIssue', '生产领料', 'production.view', 'material_issue.create', 'material_issue.review', 'material_issue.post', False),
    ('MaterialReturn', '生产退料', 'production.view', 'material_return.create', 'material_return.review', 'material_return.post', False),
    ('ProductionCompletion', '生产完工', 'production.view', 'production_completion.create', 'production_completion.review', 'production_completion.post', False),
    ('QualityDisposition', '不合格品处置', 'quality.view', 'quality.submit', 'quality.review', 'quality.post', True),
    ('MrpPlan', '物料需求计划', 'mrp.view', 'mrp.submit', 'mrp.review', 'mrp.convert', True),
    ('ProductionCostSettlement', '生产成本结算', 'production_cost.view', 'production_cost.settle', 'production_cost.review', 'production_cost.settle', False),
    ('MaintenanceJob', '设备维护工单', 'equipment.view', 'equipment.submit', 'equipment.review', 'equipment.execute', True),
    ('Journal', '总账凭证', 'journal.view', 'journal.submit', 'journal.review', 'journal.post', True),
    ('OpeningBalance', '总账期初', 'opening_balance.view', 'opening_balance.submit', 'opening_balance.review', 'opening_balance.confirm', True),
    ('SubledgerOpening', '分户期初', 'subledger_opening.view', 'subledger_opening.submit', 'subledger_opening.review', 'subledger_opening.confirm', True),
    ('PaymentRecord', '订单收付款', 'finance.view', 'finance.record', 'finance.review', 'finance.record', False),
    ('SubledgerPayment', '历史分户收付款', 'subledger_opening.view', 'finance.record', 'finance.review', 'finance.record', False),
    ('OrderSettlementTransfer', '订单间核销', 'finance.view', 'finance.record', 'finance.review', 'finance.record', False),
    ('SubledgerSettlement', '历史分户核销', 'subledger_opening.view', 'finance.record', 'finance.review', 'finance.record', False),
    ('SubledgerOrderSettlement', '历史与订单核销', 'subledger_order_settlement.view', 'finance.record', 'finance.review', 'finance.record', False),
)
APPROVAL_TYPES = {rule[0]: ApprovalType(*rule) for rule in _RULES}

# 编号范围与审批范围必须一致，防止新增单据后遗漏审核入口。
assert set(APPROVAL_TYPES) == {item[0] for item in DOCUMENT_TYPES}


def approval_step_action(step: dict) -> str:
    # 旧审批快照不能重写；缺少动作字段时仍可按原步骤名称解析按钮权限。
    if 'action' in step:
        if step['action'] not in ('review', 'verify', 'approve'):
            raise HTTPException(422, '审批步骤操作无效')
        return step['action']
    name = step['name']
    return 'verify' if '核准' in name or '复核' in name else 'approve' if '批准' in name else 'review'


def approval_type(name: str) -> ApprovalType:
    item = APPROVAL_TYPES.get(name)
    if item is None:
        raise HTTPException(422, '单据审批类型无效')
    return item
