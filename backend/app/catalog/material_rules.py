"""电子生产物料分类、永久流水号和资料变更审计。"""

import json
import re

from fastapi import HTTPException
from sqlalchemy.orm import Session, object_session
from app.catalog.specifications import specification_data
from app.catalog.categories import category_directory

from app.core.models import Material, MaterialCategory, MaterialCodeSequence, MaterialChange


# 分类代码同时作为编码前缀；名称可以调整，已分配的编码不会随分类改动。
MATERIAL_CATEGORIES = [
    {"code": "EL", "name": "电子类", "children": [
        {"code": "EL-SR", "name": "贴片电阻"},
        {"code": "EL-SC", "name": "贴片电容"},
        {"code": "EL-TR", "name": "插件电阻"},
        {"code": "EL-TC", "name": "插件电容"},
        {"code": "EL-IC", "name": "集成电路 IC"},
        {"code": "EL-DI", "name": "二极管"},
        {"code": "EL-TS", "name": "晶体管 / MOS 管"},
        {"code": "EL-IN", "name": "电感 / 磁性元件"},
        {"code": "EL-CN", "name": "连接器 / 接插件"},
        {"code": "EL-PC", "name": "PCB / 电路板"},
        {"code": "EL-CR", "name": "晶振 / 振荡器"},
        {"code": "EL-SW", "name": "开关 / 继电器"},
        {"code": "EL-WR", "name": "线材 / 线束"},
        {"code": "EL-OT", "name": "其他电子物料"}]},
    {"code": "PL", "name": "塑料类", "children": [
        {"code": "PL-HS", "name": "塑料外壳"},
        {"code": "PL-ST", "name": "塑料结构件"},
        {"code": "PL-OT", "name": "其他塑料件"}]},
    {"code": "HW", "name": "五金类", "children": [
        {"code": "HW-FA", "name": "螺丝 / 紧固件"},
        {"code": "HW-ST", "name": "五金结构件"},
        {"code": "HW-HS", "name": "散热件"},
        {"code": "HW-OT", "name": "其他五金件"}]},
    {"code": "PK", "name": "包装类", "children": [
        {"code": "PK-OT", "name": "包装材料"}]},
    {"code": "OT", "name": "其他类", "children": [
        {"code": "OT-OT", "name": "其他物料"}]}
]
CATEGORY_CODES = {child['code'] for group in MATERIAL_CATEGORIES for child in group['children']}
DETAIL_FIELDS = ('category_code', 'specification', 'package', 'brand', 'manufacturer_part_number',
                 'electrical_value', 'tolerance', 'rated_voltage', 'rated_power',
                 'temperature_range', 'compliance', 'notes')
MATERIAL_FIELDS = ('id', 'sku', 'name', 'unit', *DETAIL_FIELDS, 'version')


def material_data(material: Material) -> dict:
    return {**{key: getattr(material, key) for key in MATERIAL_FIELDS}, **specification_data(material)}


def material_choice_data(material: Material) -> dict:
    # 业务选料只附带辨认资料，不带编辑版本、供应商联系方式或业务价格。
    result = {key: getattr(material, key) for key in ('id', 'sku', 'name', 'unit', *DETAIL_FIELDS)}
    db = object_session(material)
    directory = category_directory(db) if db is not None else {}
    child = directory.get(material.category_code)
    parent = directory.get(child['parent_code']) if child else None
    result['category_name'] = f"{parent['name']} / {child['name']}" if child and parent else '未分类'
    result.update(specification_data(material))
    return result


def allocate_material_code(db: Session, category: str) -> str:
    # 调用方已持有 BEGIN IMMEDIATE 写锁，流水和物料在同一事务提交，失败一起回滚。
    sequence = db.get(MaterialCodeSequence, category)
    if sequence is None:
        sequence = MaterialCodeSequence(prefix=category, last_number=0)
        db.add(sequence)
    number = sequence.last_number + 1
    if number > 999999:
        raise HTTPException(409, '此物料子类的六位流水号已用完')
    sequence.last_number = number
    return f'{category}-{number:06d}'


def reserve_legacy_code(db: Session, sku: str) -> None:
    # 旧客户端手工编码若与系统格式相同，也登记流水，删除后不重复分配。
    match = re.fullmatch(r'([A-Z]{2,4}-[A-Z]{2,4})-(\d{6})', sku)
    if match and match[1] in category_directory(db):
        # 旧客户端占用了该前缀的流水，也视为已使用类别，不能随后移除。
        db.get(MaterialCategory, match[1]).used = True
        sequence = db.get(MaterialCodeSequence, match[1])
        if sequence is None:
            db.add(MaterialCodeSequence(prefix=match[1], last_number=int(match[2])))
        else:
            sequence.last_number = max(sequence.last_number, int(match[2]))


def record_material_change(db: Session, material: Material, action: str,
                           before: dict | None, actor: dict, reason: str,
                           *, supplier_ids: list[int] | None = None) -> None:
    # 不设置物料外键，删除未被引用的档案后仍可保留原编码及完整变更证据。
    after = material_data(material)
    if supplier_ids is not None:
        # 供货关系变更与物料版本共用审计，旧调用仍保留原快照格式。
        after['supplier_ids'] = supplier_ids
    db.add(MaterialChange(material_id=material.id, sku=material.sku, action=action,
        before_json=json.dumps(before, ensure_ascii=False) if before is not None else None,
        after_json=json.dumps(after, ensure_ascii=False) if action != 'delete' else None,
        changed_by=actor['id'], reason=reason))
