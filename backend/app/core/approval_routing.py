"""审批金额条件：只使用领域已固定的正文，不读取客户端金额或实时余额。"""

import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from fastapi import HTTPException


AMOUNT_BASES = {
    'PurchaseRequest': '申请逐行金额合计',
    'PurchaseOrder': '订单逐行金额合计',
    'SalesOrder': '订单逐行金额合计',
    'CrmQuote': '报价逐行金额合计',
    'Journal': '凭证借方合计',
    'ProductionCostSettlement': '结算计划总成本',
    **{name: '本单金额绝对值' for name in ('PaymentRecord', 'SubledgerPayment',
        'OrderSettlementTransfer', 'SubledgerSettlement', 'SubledgerOrderSettlement',
        'ControlBalanceTransfer')},
}
LIMIT = Decimal('1000000000000000000')
CENT = Decimal('.01')


def boundary(value) -> Decimal:
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9][0-9]{0,18})(\.[0-9]{1,2})?', value):
        raise HTTPException(422, '金额界限须为非负金额文本，最多两位小数')
    result = Decimal(value)
    if result > LIMIT:
        raise HTTPException(422, '金额界限超过允许范围')
    return result


def validate_branches(db, document_type: str, branches, validate_steps) -> list[dict]:
    if not isinstance(branches, list) or len(branches) > 5:
        raise HTTPException(422, '金额分支最多五个')
    if branches and document_type not in AMOUNT_BASES:
        raise HTTPException(422, '此类单据没有可用于审批分支的固定金额')
    checked, names = [], set()
    for branch in branches:
        if (not isinstance(branch, Mapping) or set(branch) != {'name', 'min_amount', 'max_amount', 'steps'}
                or not isinstance(branch['name'], str) or not 1 <= len(branch['name'].strip()) <= 40):
            raise HTTPException(422, '金额分支名称或字段无效')
        name = branch['name'].strip()
        if name in names:
            raise HTTPException(422, '金额分支名称不能重复')
        names.add(name)
        low = boundary(branch['min_amount'])
        high = None if branch['max_amount'] is None else boundary(branch['max_amount'])
        if high is not None and high <= low:
            raise HTTPException(422, '金额上限须大于下限')
        for other in checked:
            if ((other['max_amount'] is None or low < Decimal(other['max_amount']))
                    and (high is None or Decimal(other['min_amount']) < high)):
                raise HTTPException(422, '金额分支区间不能重叠')
        checked.append({'name': name, 'min_amount': format(low, '.2f'),
            'max_amount': None if high is None else format(high, '.2f'),
            'steps': validate_steps(db, branch['steps'])})
    return checked


def number(value, *, signed=False) -> Decimal:
    # 正文损坏或尚未核价时拒绝送审，不能退回默认分支或把未知金额当作零。
    try:
        if not isinstance(value, str):
            raise ValueError()
        result = Decimal(value)
        if not result.is_finite() or not (-LIMIT if signed else 0) <= result <= LIMIT:
            raise ValueError()
        return result
    except (InvalidOperation, ValueError):
        raise HTTPException(409, '单据金额尚未完整确定，不能选择金额审批分支') from None


def snapshot_amount(document_type: str, content: Mapping) -> Decimal:
    try:
        if document_type in ('PurchaseRequest', 'PurchaseOrder', 'SalesOrder', 'CrmQuote'):
            lines = content['lines']
            if not lines:
                raise ValueError()
            amounts = [number(line['line_total']) if line.get('pricing_mode') == 'total'
                else (number(line['quantity']) * number(line['unit_price'])).quantize(CENT, rounding=ROUND_HALF_UP)
                for line in lines]
            result = sum(amounts, Decimal(0))
        elif document_type == 'Journal':
            # 借贷合计只能计一侧，避免一张平衡凭证的额度被重复计算。
            result = sum((number(line['debit']) for line in content['lines']), Decimal(0))
        elif document_type == 'ProductionCostSettlement':
            result = number(content['plan']['header']['total_amount'])
        elif document_type in AMOUNT_BASES:
            # 退款及独立反向单据保留原符号，审批额度比较本次经济金额的绝对值。
            result = number(content['amount'], signed=True).copy_abs()
        else:
            raise ValueError()
        if result > LIMIT:
            raise ValueError()
        return result.quantize(CENT, rounding=ROUND_HALF_UP)
    except (KeyError, TypeError, ValueError, InvalidOperation):
        raise HTTPException(409, '单据缺少完整的金额依据，不能选择金额审批分支') from None


def resolve(document_type: str, content: Mapping, intent: str, default_steps: list, branches: list):
    if not branches:
        return default_steps, None
    if intent == 'reverse':
        # 更正流程沿用默认步骤；原审批金额不能代替本次更正的风险判断。
        return default_steps, {'mode': 'reverse_default', 'basis': AMOUNT_BASES[document_type],
            'amount': None, 'branch': None, 'rules': branches}
    amount = snapshot_amount(document_type, content)
    branch = next((row for row in branches if Decimal(row['min_amount']) <= amount
        and (row['max_amount'] is None or amount < Decimal(row['max_amount']))), None)
    return (branch['steps'] if branch else default_steps), {
        'mode': 'amount', 'basis': AMOUNT_BASES[document_type], 'amount': format(amount, '.2f'),
        'branch': None if branch is None else {key: branch[key] for key in ('name', 'min_amount', 'max_amount')},
        'rules': branches}
