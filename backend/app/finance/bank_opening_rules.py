"""银行期初未达项的有效核销证据。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import (BankOpeningClearance, BankOpeningClearanceMember,
    BankOpeningClearanceReversal, BankOpeningItem)


def active_clearances(db: Session, account_id: int) -> list[tuple[BankOpeningClearance, BankOpeningItem, list[BankOpeningClearanceMember]]]:
    items = {item.id: item for item in db.scalars(select(BankOpeningItem).where(
        BankOpeningItem.account_id == account_id))}
    if not items:
        return []
    clearances = list(db.scalars(select(BankOpeningClearance).where(
        BankOpeningClearance.opening_item_id.in_(items)).order_by(BankOpeningClearance.id)))
    if not clearances:
        return []
    reversed_ids = set(db.scalars(select(BankOpeningClearanceReversal.clearance_id).where(
        BankOpeningClearanceReversal.clearance_id.in_([item.id for item in clearances]))))
    members: dict[int, list[BankOpeningClearanceMember]] = {}
    for member in db.scalars(select(BankOpeningClearanceMember).where(
        BankOpeningClearanceMember.clearance_id.in_([item.id for item in clearances]))):
        members.setdefault(member.clearance_id, []).append(member)
    return [(item, items[item.opening_item_id], members.get(item.id, []))
        for item in clearances if item.id not in reversed_ids]
