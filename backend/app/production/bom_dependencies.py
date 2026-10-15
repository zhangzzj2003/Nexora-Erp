"""多层配方只约束生产依据，实际领料仍以独立物料库存为边界。"""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Bom, BomLine


def validate_component_bom(db: Session, material_id: int, bom_id: int | None) -> None:
    if bom_id is None:
        return
    child = db.get(Bom, bom_id)
    if child is None or child.product_material_id != material_id or child.status not in ('active', 'retired'):
        raise HTTPException(422, '组件配方须属于该组件物料，且已经启用过')


def require_bom_ready(db: Session, bom_id: int, *, draft_root: bool = False) -> None:
    # 配方版本固定引用；下层停用后须显式修订上层，不能自动换成最新版本。
    heights: dict[int, int] = {}
    def visit(identifier: int, material_path: frozenset[int], depth: int) -> int:
        bom = db.get(Bom, identifier)
        if bom is None:
            raise HTTPException(409, '引用的 BOM 不存在')
        if bom.product_material_id in material_path or depth > 20:
            raise HTTPException(409, 'BOM 存在循环引用或超过 20 层')
        if not (draft_root and depth == 0) and bom.status != 'active':
            raise HTTPException(409, f'引用的 BOM #{bom.id} V{bom.version} 已停用，请修订上层 BOM 后再生产')
        # 共享组件只校验一次，缓存子树高度仍可检查另一条更长路径，避免组合爆炸。
        if identifier in heights:
            if depth + heights[identifier] > 20:
                raise HTTPException(409, 'BOM 超过 20 层')
            return heights[identifier]
        path = material_path | {bom.product_material_id}
        height = 0
        for line in db.scalars(select(BomLine).where(BomLine.bom_id == bom.id)):
            validate_component_bom(db, line.component_material_id, line.component_bom_id)
            if line.component_material_id in path:
                raise HTTPException(409, 'BOM 存在循环引用')
            if line.component_bom_id is not None:
                height = max(height, 1 + visit(line.component_bom_id, path, depth + 1))
        heights[identifier] = height
        return height
    visit(bom_id, frozenset(), 0)
