"""仓库名称编码与现存物料种数；不改写历史编码或库存流水。"""

import re
import unicodedata
from decimal import Decimal

from pypinyin import Style, lazy_pinyin
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import StockMovement, Warehouse


def next_warehouse_code(db: Session, name: str) -> str:
    # 中文取词组读音的首字母，英文与数字保留；纯符号名称使用稳定的仓库前缀。
    initials = ''.join(lazy_pinyin(name, style=Style.FIRST_LETTER))
    normalized = unicodedata.normalize('NFKD', initials).encode('ascii', 'ignore').decode()
    base = re.sub(r'[^A-Z0-9]', '', normalized.upper())[:40] or 'CK'
    existing = {code.upper() for code in db.scalars(select(Warehouse.code))}
    candidate, sequence = base, 2
    # 正式创建在串行写事务中重算；预览不占号，并发新增也不会复用同一编码。
    while candidate in existing:
        suffix = f'-{sequence}'
        candidate = base[:40 - len(suffix)] + suffix
        sequence += 1
    return candidate


def warehouse_material_counts(db: Session) -> dict[int, int]:
    # 数量是十进制文本，沿用库存查询的 Decimal 求和，避免浮点残差把零库存算作有货。
    balances: dict[tuple[int, int], Decimal] = {}
    for warehouse_id, material_id, quantity in db.execute(select(
            StockMovement.warehouse_id, StockMovement.material_id, StockMovement.quantity)):
        key = (warehouse_id, material_id)
        balances[key] = balances.get(key, Decimal(0)) + Decimal(quantity)
    counts: dict[int, int] = {}
    for (warehouse_id, _), quantity in balances.items():
        if quantity > 0:
            counts[warehouse_id] = counts.get(warehouse_id, 0) + 1
    return counts
