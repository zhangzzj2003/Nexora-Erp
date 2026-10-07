"""本机维护工具：显式指定实例、备份与审计管理员后导入虚构物料。"""

import argparse
import json
import os
from pathlib import Path

from sqlalchemy import select
from fastapi import HTTPException

from app.access.security import user_details
from app.catalog.material_rules import DETAIL_FIELDS, allocate_material_code, record_material_change
from app.catalog.routes import MaterialInput
from app.catalog.categories import validate_selection
from app.catalog.specifications import save_specifications
from app.core.models import Material, ServerIdentity
from app.core.orm import orm_session
from app.service.backup import create_backup

MARKER = 'NEXORA-DEMO-MATERIALS-V1'


def load_materials(path: Path) -> list[MaterialInput]:
    """完整预检后再写库，防止中间一条非法数据造成部分导入。"""
    raw = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(raw, list) or not 1 <= len(raw) <= 1000:
        raise ValueError('演示物料必须为包含 1～1000 条记录的数组')
    rows = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict) or set(item) - MaterialInput.model_fields.keys():
            raise ValueError('演示物料字段不符合现有接口契约')
        row = MaterialInput.model_validate(item)
        if (row.sku or row.version is not None or not row.category_code
                or not row.name.startswith('示例 · ')
                or not row.manufacturer_part_number.startswith('DEMO-') or MARKER not in row.notes):
            raise ValueError('只能导入带稳定示例标识、由系统分配编码的物料')
        if row.manufacturer_part_number in seen:
            raise ValueError('演示料号重复')
        seen.add(row.manufacturer_part_number)
        rows.append(row)
    return rows


def import_materials(rows: list[MaterialInput], actor_id: int, instance_id: str) -> dict[str, int]:
    # 这是持有数据库文件访问权的本机维护入口，不暴露为网络接口，不建立或修改登录会话。
    # 使用现有写事务、编码分配和资料审计；任一冲突或审计失败会回滚整批。
    with orm_session(write=True) as db:
        if db.scalar(select(ServerIdentity.id)) != instance_id:
            raise ValueError('目标实例身份不匹配，未导入')
        actor = user_details(db, actor_id)
        if not actor['is_active'] or 'admin' not in actor['roles'] or 'catalog.manage' not in actor['permissions']:
            raise ValueError('审计操作者必须是启用且具备物料管理权限的现有管理员')
        existing = list(db.scalars(select(Material).where(Material.manufacturer_part_number.in_(
            [row.manufacturer_part_number for row in rows]))))
        by_part = {}
        for material in existing:
            if (material.manufacturer_part_number in by_part or MARKER not in material.notes
                    or not material.name.startswith('示例 · ')):
                raise ValueError('演示料号与已有档案冲突，未导入')
            by_part[material.manufacturer_part_number] = material
        created = skipped = 0
        for row in rows:
            if row.manufacturer_part_number in by_part:
                # 保留用户已经编辑过的示例档案，重跑不覆盖、不追加重复审计、不占用编码。
                skipped += 1
                continue
            material = Material(sku=allocate_material_code(db, row.category_code), name=row.name,
                unit=row.unit, **{key: getattr(row, key) for key in DETAIL_FIELDS}, version=1)
            # 本机导入与界面共用动态分类和规格约束，不能绕过停用或必填规则。
            material.spec_values_json, material.extra_attributes_json, material.spec_template_version = '[]', '[]', 0
            try:
                validate_selection(db, row.category_code)
                save_specifications(db, material, row.spec_values, row.spec_template_version,
                                    row.extra_attributes, validate_required=True)
            except HTTPException as error:
                raise ValueError(str(error.detail)) from None
            db.add(material)
            db.flush()
            record_material_change(db, material, 'create', None, actor,
                row.reason or '导入物料演示数据')
            created += 1
        return {'created': created, 'skipped': skipped}


def main() -> None:
    parser = argparse.ArgumentParser(description='导入物料演示数据（仅本机维护，不自动执行）')
    parser.add_argument('--data-dir', required=True, type=Path)
    parser.add_argument('--instance-id', required=True)
    parser.add_argument('--actor-user-id', required=True, type=int)
    parser.add_argument('--backup', required=True, type=Path)
    parser.add_argument('--materials', type=Path, default=Path(__file__).with_name('materials.json'))
    args = parser.parse_args()
    if not args.data_dir.is_absolute() or not (args.data_dir / 'nexora.db').is_file():
        parser.error('必须提供现有实例的绝对数据目录，工具不创建数据库或执行升级')
    os.environ['NEXORA_DB_PATH'] = str(args.data_dir / 'nexora.db')
    rows = load_materials(args.materials)
    # 备份同时保留数据库、证书和私钥；身份校验后才允许进入批量写事务。
    if create_backup(args.data_dir, args.backup) != args.instance_id:
        raise ValueError('备份实例身份不匹配，未导入')
    result = import_materials(rows, args.actor_user_id, args.instance_id)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
