"""客户名称的保守相似匹配；结果仅用于人工核对。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Customer
from app.sales.customer_scope import visible_customers


def comparable_customer_name(name: str) -> str:
    # 仅消除大小写、空白和标点差异；不擅自推断简称、法人主体或关联公司。
    return ''.join(char for char in name.casefold() if char.isalnum())


def name_match(left: str, right: str) -> str | None:
    first, second = comparable_customer_name(left), comparable_customer_name(right)
    if not first or not second:
        return None
    if first == second:
        return 'same_name'
    if min(len(first), len(second)) >= 4 and (first in second or second in first):
        return 'similar_name'
    return None


def visible_name_rows(db: Session, user: dict) -> list[tuple[int, str]]:
    return list(db.execute(visible_customers(
        select(Customer.id, Customer.name).order_by(Customer.id), user)).all())


def duplicate_candidates(name: str, rows: list[tuple[int, str]]) -> list[dict]:
    candidates = [{'id': identifier, 'name': existing, 'match': match}
                  for identifier, existing in rows
                  if (match := name_match(name, existing))]
    candidates.sort(key=lambda row: (row['match'] != 'same_name', row['id']))
    return candidates[:10]
