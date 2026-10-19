"""日期分桶的 MRP 运算；纯 Decimal，不持有数据库或改变库存。"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING

from fastapi import HTTPException

ZERO = Decimal(0)
STEP = Decimal('0.001')


def quantity(value: Decimal) -> str:
    return format(value.quantize(STEP), 'f')


def calculate(snapshot: dict, start_date: str, demand_dates: dict[str, str], supply_dates: dict[str, str],
              manual_demands: list[dict]) -> dict:
    materials = {row['id']: row for row in snapshot['materials']}
    policies = {row['material_id']: row for row in snapshot['policies']}
    boms = {row['product_material_id']: row for row in snapshot['boms']}
    restrictions = {row['material_id']: row for row in snapshot.get('product_restrictions', [])}
    modes = {identifier: policies[identifier]['supply_mode'] for identifier in materials}
    modes = {identifier: ('make' if identifier in boms else 'buy') if mode == 'auto' else mode
             for identifier, mode in modes.items()}
    for identifier, mode in modes.items():
        if mode == 'make' and identifier not in boms:
            raise HTTPException(409, f"物料 {materials[identifier]['sku']} 配置为生产，但没有启用 BOM")
    # 用全图低层码顺序归并共享组件，不能逐根树分别扣同一份库存。
    children = {identifier: [line['component_material_id'] for line in boms[identifier]['lines']]
                if modes[identifier] == 'make' else [] for identifier in materials}
    indegrees = {identifier: 0 for identifier in materials}
    for edges in children.values():
        for child in edges:
            if child not in materials:
                raise HTTPException(409, 'BOM 引用了不存在的物料')
            indegrees[child] += 1
    levels = {identifier: 0 for identifier in materials}
    ready = sorted(identifier for identifier, degree in indegrees.items() if degree == 0)
    ordered = []
    while ready:
        parent = ready.pop(0)
        ordered.append(parent)
        for child in children[parent]:
            levels[child] = max(levels[child], levels[parent] + 1)
            if levels[child] > 20:
                raise HTTPException(422, 'BOM 超过 20 层，请先整理产品结构')
            indegrees[child] -= 1
            if indegrees[child] == 0:
                ready.append(child)
                ready.sort()
    if len(ordered) != len(materials):
        raise HTTPException(409, '有效生产 BOM 存在循环，不能计算物料计划')
    demands: dict[int, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    supplies: dict[int, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for source in snapshot['demands']:
        demands[source['material_id']][demand_dates[source['key']]].append(source)
    for index, source in enumerate(manual_demands, 1):
        demands[source['material_id']][source['due_date']].append({**source, 'key': f'manual:{index}', 'kind': 'manual'})
    for source in snapshot['reservations']:
        # 新计划及其工单按保存的开工日需料；历史工单继续按本次起日计算。
        demands[source['material_id']][max(start_date, source.get('due_date') or start_date)].append(source)
    rows, suggestions, warnings = [], [], []
    for source in snapshot['supplies']:
        due = source.get('due_date') or supply_dates[source['key']]
        # 以前计划的未完成供给已经逾期时，明确展示逾期并按今天最早可到处理。
        supplies[source['material_id']][max(start_date, due)].append({**source, 'scheduled_date': due})
        if due < start_date:
            warnings.append(f"供给 {source['key']} 原安排日 {due} 已过期，按计划起日 {start_date} 预计到达，须核实原单交期")
    on_hand = defaultdict(lambda: ZERO)
    for source in snapshot['movements']:
        on_hand[source['material_id']] += Decimal(source['quantity'])
    for identifier in ordered:
        policy = policies[identifier]
        safety = Decimal(policy['safety_stock'])
        balance = on_hand[identifier]
        dates = set(demands[identifier]) | set(supplies[identifier])
        if safety > 0:
            dates.add(start_date)
        for due in sorted(dates):
            required = demands[identifier][due]
            incoming = supplies[identifier][due]
            gross = sum((Decimal(row['quantity']) for row in required), ZERO)
            scheduled = sum((Decimal(row['quantity']) for row in incoming), ZERO)
            before = balance
            net = max(ZERO, gross + safety - balance - scheduled)
            planned = ZERO
            suggestion = None
            if net > 0:
                # 计划建议与真实转单使用相同的用途约束，不能推荐无法执行的采购或生产。
                capability = 'can_produce' if modes[identifier] == 'make' else 'can_purchase'
                if not restrictions.get(identifier, {}).get(capability, True):
                    raise HTTPException(409, f"物料 {materials[identifier]['sku']} 未允许{'生产' if capability == 'can_produce' else '采购'}，请调整产品用途或供给方式")
                planned = max(net, Decimal(policy['minimum_quantity']))
                multiple = Decimal(policy['multiple_quantity'])
                if multiple > 0:
                    planned = (planned / multiple).to_integral_value(rounding=ROUND_CEILING) * multiple
                planned = planned.quantize(STEP, rounding=ROUND_CEILING)
                if planned > 1_000_000:
                    raise HTTPException(422, f"物料 {materials[identifier]['sku']} 单日建议超过一百万，须拆分需求日期")
                required_release = (date.fromisoformat(due) - timedelta(days=policy['lead_time_days'])).isoformat()
                release = max(start_date, required_release)
                key = f'{identifier}:{due}'
                suggestion = {'key': key, 'material_id': identifier, 'supply_mode': modes[identifier],
                    'quantity': quantity(planned), 'due_date': due, 'release_date': release,
                    'required_release_date': required_release, 'late': required_release < start_date,
                    'bom_id': boms[identifier]['id'] if modes[identifier] == 'make' else None,
                    'bom_version': boms[identifier]['version'] if modes[identifier] == 'make' else None,
                    **{key: materials[identifier][key] for key in ('sku', 'name', 'unit')}}
                suggestions.append(suggestion)
                if suggestion['late']:
                    warnings.append(f"{materials[identifier]['sku']} {due} 的供给需在 {required_release} 投放，投放日早于计划起日，提前期不足")
                if modes[identifier] == 'make':
                    bom = boms[identifier]
                    for line in bom['lines']:
                        needed = (planned * Decimal(line['quantity']) / Decimal(bom['base_quantity'])).quantize(
                            STEP, rounding=ROUND_CEILING)
                        if needed > 1_000_000:
                            raise HTTPException(422, '建议工单的单组件需求超过一百万，须拆分需求日期')
                        demands[line['component_material_id']][release].append({'key': f'bom:{key}:{line["id"]}',
                            'kind': 'planned_work_order', 'parent_key': key, 'bom_id': bom['id'],
                            'bom_version': bom['version'], 'material_id': line['component_material_id'],
                            'quantity': quantity(needed)})
            balance = balance + scheduled + planned - gross
            rows.append({'material_id': identifier, **{key: materials[identifier][key] for key in ('sku', 'name', 'unit')},
                'date': due, 'level': levels[identifier], 'supply_mode': modes[identifier],
                'opening_quantity': quantity(before), 'gross_quantity': quantity(gross),
                'scheduled_quantity': quantity(scheduled), 'safety_stock': quantity(safety),
                'net_quantity': quantity(net), 'planned_quantity': quantity(planned), 'closing_quantity': quantity(balance),
                'demand_sources': required, 'supply_sources': incoming,
                'suggestion_key': suggestion['key'] if suggestion else None})
            if len(rows) > 5000 or len(suggestions) > 1000:
                raise HTTPException(422, '计划超过 5000 日期行或 1000 建议，请整理需求日期后重算')
    return {'rows': rows, 'suggestions': suggestions, 'warnings': warnings,
        'assumptions': ['单公司全部仓库合并数量，不代表目标仓库可立即发料',
            '同日先到货再需求；在途采购及工单剩余报工量属于预计供给，不保证按期或全部合格',
            '采购申请及未下达的计划工单属于待执行供给，须完成原单审批或下达',
            '提前期按日历日；逾期建议明确告警，不推断产能、工作日、损耗或实际交期']}
