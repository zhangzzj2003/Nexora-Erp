"""业务 ORM 模型；金额保留文本精度，库结构由版本迁移维护。"""

from sqlalchemy import ForeignKey, Integer, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class LedgerAccount(Base):
    __tablename__ = 'ledger_accounts'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    normal_balance: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class AccountingPeriod(Base):
    __tablename__ = 'accounting_periods'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[str] = mapped_column(Text, nullable=False)
    end_date: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class LedgerAccountChange(Base):
    __tablename__ = 'ledger_account_changes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey('ledger_accounts.id'), nullable=False)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class AccountingPeriodChange(Base):
    __tablename__ = 'accounting_period_changes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey('accounting_periods.id'), nullable=False)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class PeriodClosing(Base):
    __tablename__ = 'period_closings'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey('accounting_periods.id'), nullable=False)
    period_version: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class Journal(Base):
    __tablename__ = 'journals'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    journal_date: Mapped[str] = mapped_column(Text, nullable=False)
    period_id: Mapped[int] = mapped_column(ForeignKey('accounting_periods.id'), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'CNY'"))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    reversal_of_id: Mapped[int | None] = mapped_column(ForeignKey('journals.id'))
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    posted_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    cancelled_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    submitted_at: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[str | None] = mapped_column(Text)


class JournalLine(Base):
    __tablename__ = 'journal_lines'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    journal_id: Mapped[int] = mapped_column(ForeignKey('journals.id'), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey('ledger_accounts.id'), nullable=False)
    account_code: Mapped[str] = mapped_column(Text, nullable=False)
    account_name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    normal_balance: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    debit: Mapped[str] = mapped_column(Text, nullable=False)
    credit: Mapped[str] = mapped_column(Text, nullable=False)


class JournalChange(Base):
    __tablename__ = 'journal_changes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    journal_id: Mapped[int] = mapped_column(ForeignKey('journals.id'), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class BusinessJournalPolicy(Base):
    __tablename__ = 'business_journal_policies'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    start_date: Mapped[str] = mapped_column(Text, nullable=False)
    mapping_json: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class BusinessJournalPolicyChange(Base):
    __tablename__ = 'business_journal_policy_changes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class BusinessJournalSource(Base):
    __tablename__ = 'business_journal_sources'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    journal_id: Mapped[int] = mapped_column(ForeignKey('journals.id'), nullable=False, unique=True)
    source_key: Mapped[str] = mapped_column(Text, nullable=False)
    active_key: Mapped[str | None] = mapped_column(Text, unique=True)
    source_json: Mapped[str] = mapped_column(Text, nullable=False)
    mapping_json: Mapped[str] = mapped_column(Text, nullable=False)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class ProfitTransferPolicy(Base):
    __tablename__ = 'profit_transfer_policies'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    start_date: Mapped[str] = mapped_column(Text, nullable=False)
    target_account_id: Mapped[int] = mapped_column(ForeignKey('ledger_accounts.id'), nullable=False)
    cost_account_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class ProfitTransferPolicyChange(Base):
    __tablename__ = 'profit_transfer_policy_changes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class ProfitTransfer(Base):
    __tablename__ = 'profit_transfers'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    journal_id: Mapped[int] = mapped_column(ForeignKey('journals.id'), nullable=False, unique=True)
    period_id: Mapped[int] = mapped_column(ForeignKey('accounting_periods.id'), nullable=False)
    active_period_id: Mapped[int | None] = mapped_column(ForeignKey('accounting_periods.id'), unique=True)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False)
    policy_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class OpeningBalance(Base):
    __tablename__ = 'opening_balances'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    effective_date: Mapped[str] = mapped_column(Text, nullable=False)
    period_id: Mapped[int] = mapped_column(ForeignKey('accounting_periods.id'), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'CNY'"))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    active_key: Mapped[int | None] = mapped_column(Integer, unique=True)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    cancelled_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    reversed_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    submitted_at: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[str | None] = mapped_column(Text)
    reversed_at: Mapped[str | None] = mapped_column(Text)


class OpeningBalanceLine(Base):
    __tablename__ = 'opening_balance_lines'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opening_balance_id: Mapped[int] = mapped_column(ForeignKey('opening_balances.id'), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey('ledger_accounts.id'), nullable=False)
    account_code: Mapped[str] = mapped_column(Text, nullable=False)
    account_name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    normal_balance: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    debit: Mapped[str] = mapped_column(Text, nullable=False)
    credit: Mapped[str] = mapped_column(Text, nullable=False)


class OpeningBalanceChange(Base):
    __tablename__ = 'opening_balance_changes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opening_balance_id: Mapped[int] = mapped_column(ForeignKey('opening_balances.id'), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('1'))
    full_name: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    employee_no: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    phone: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))


class Material(Base):
    __tablename__ = 'materials'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class Role(Base):
    __tablename__ = 'roles'
    code: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    is_builtin: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))


class PermissionGroup(Base):
    __tablename__ = 'permission_groups'
    code: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    parent_code: Mapped[str | None] = mapped_column(Text, ForeignKey('permission_groups.code'))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class Permission(Base):
    __tablename__ = 'permissions'
    code: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    group_code: Mapped[str | None] = mapped_column(Text, ForeignKey('permission_groups.code'))


class RolePermission(Base):
    __tablename__ = 'role_permissions'
    role_code: Mapped[str] = mapped_column(Text, ForeignKey('roles.code'), primary_key=True)
    permission_code: Mapped[str] = mapped_column(Text, ForeignKey('permissions.code'), primary_key=True)


class UserRole(Base):
    __tablename__ = 'user_roles'
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), primary_key=True)
    role_code: Mapped[str] = mapped_column(Text, ForeignKey('roles.code'), primary_key=True)


class AuthSession(Base):
    __tablename__ = 'sessions'
    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    expires_at: Mapped[int] = mapped_column(Integer, nullable=False)


class UserProfileChange(Base):
    __tablename__ = 'user_profile_changes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    changed_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    before_json: Mapped[str] = mapped_column(Text, nullable=False)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class MenuIcon(Base):
    __tablename__ = 'menu_icons'
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    icon: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class MenuIconChange(Base):
    __tablename__ = 'menu_icon_changes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    menu_key: Mapped[str] = mapped_column(Text, nullable=False)
    before_icon: Mapped[str | None] = mapped_column(Text)
    after_icon: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class Supplier(Base):
    __tablename__ = 'suppliers'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class SupplierMaterial(Base):
    __tablename__ = 'supplier_materials'
    supplier_id: Mapped[int] = mapped_column(Integer, ForeignKey('suppliers.id', ondelete='CASCADE'), primary_key=True)
    material_id: Mapped[int] = mapped_column(Integer, ForeignKey('materials.id', ondelete='CASCADE'), primary_key=True)


class Warehouse(Base):
    __tablename__ = 'warehouses'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(Text(collation='NOCASE'), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class ServerIdentity(Base):
    __tablename__ = 'server_identity'
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class Bom(Base):
    __tablename__ = 'boms'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_material_id: Mapped[int] = mapped_column(Integer, ForeignKey('materials.id'), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    base_quantity: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    activated_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    retired_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    cancelled_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    activated_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    retired_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class WorkOrder(Base):
    __tablename__ = 'work_orders'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bom_id: Mapped[int] = mapped_column(Integer, ForeignKey('boms.id'), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(Integer, nullable=False)
    target_quantity: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    released_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    cancelled_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    released_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    completed_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class WorkOrderLine(Base):
    __tablename__ = 'work_order_lines'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    work_order_id: Mapped[int] = mapped_column(Integer, ForeignKey('work_orders.id'), nullable=False)
    component_material_id: Mapped[int] = mapped_column(Integer, ForeignKey('materials.id'), nullable=False)
    required_quantity: Mapped[str] = mapped_column(Text, nullable=False)


class MaterialIssue(Base):
    __tablename__ = 'material_issues'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    work_order_id: Mapped[int] = mapped_column(Integer, ForeignKey('work_orders.id'), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(Integer, nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    posted_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    cancelled_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    posted_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class MaterialIssueLine(Base):
    __tablename__ = 'material_issue_lines'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    material_issue_id: Mapped[int] = mapped_column(Integer, ForeignKey('material_issues.id'), nullable=False)
    work_order_line_id: Mapped[int] = mapped_column(Integer, ForeignKey('work_order_lines.id'), nullable=False)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)


class MaterialReturn(Base):
    __tablename__ = 'material_returns'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    material_issue_id: Mapped[int] = mapped_column(Integer, ForeignKey('material_issues.id'), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    posted_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    cancelled_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    posted_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class MaterialReturnLine(Base):
    __tablename__ = 'material_return_lines'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    material_return_id: Mapped[int] = mapped_column(Integer, ForeignKey('material_returns.id'), nullable=False)
    material_issue_line_id: Mapped[int] = mapped_column(Integer, ForeignKey('material_issue_lines.id'), nullable=False)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)


class ProductionCompletion(Base):
    __tablename__ = 'production_completions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    work_order_id: Mapped[int] = mapped_column(Integer, ForeignKey('work_orders.id'), nullable=False)
    reported_quantity: Mapped[str] = mapped_column(Text, nullable=False)
    accepted_quantity: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejected_quantity: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    qc_note: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    inspected_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    posted_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    cancelled_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    inspected_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProductionCompletionReversal(Base):
    __tablename__ = 'production_completion_reversals'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    production_completion_id: Mapped[int] = mapped_column(Integer, ForeignKey('production_completions.id'), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class ProductionCostEntry(Base):
    __tablename__ = 'production_cost_entries'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    work_order_id: Mapped[int] = mapped_column(Integer, ForeignKey('work_orders.id'), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    material_issue_line_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('material_issue_lines.id'), nullable=True)
    unit_cost: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class ProductionCostReversal(Base):
    __tablename__ = 'production_cost_reversals'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(Integer, ForeignKey('production_cost_entries.id'), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class ProductionCostSettlement(Base):
    __tablename__ = 'production_cost_settlements'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    work_order_id: Mapped[int] = mapped_column(Integer, ForeignKey('work_orders.id'), nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    material_amount: Mapped[str] = mapped_column(Text, nullable=False)
    labor_amount: Mapped[str] = mapped_column(Text, nullable=False)
    overhead_amount: Mapped[str] = mapped_column(Text, nullable=False)
    total_amount: Mapped[str] = mapped_column(Text, nullable=False)
    accepted_quantity: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class ProductionSettlementReversal(Base):
    __tablename__ = 'production_settlement_reversals'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    settlement_id: Mapped[int] = mapped_column(Integer, ForeignKey('production_cost_settlements.id'), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class ProductionCostAllocation(Base):
    __tablename__ = 'production_cost_allocations'
    settlement_id: Mapped[int] = mapped_column(Integer, ForeignKey('production_cost_settlements.id'), primary_key=True)
    completion_id: Mapped[int] = mapped_column(Integer, ForeignKey('production_completions.id'), nullable=False)
    movement_id: Mapped[int] = mapped_column(Integer, ForeignKey('stock_movements.id'), primary_key=True)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[str] = mapped_column(Text, nullable=False)


class ProductionSettlementSource(Base):
    __tablename__ = 'production_settlement_sources'
    settlement_id: Mapped[int] = mapped_column(Integer, ForeignKey('production_cost_settlements.id'), primary_key=True)
    material_issue_line_id: Mapped[int] = mapped_column(Integer, ForeignKey('material_issue_lines.id'), primary_key=True)
    movement_id: Mapped[int] = mapped_column(Integer, ForeignKey('stock_movements.id'), nullable=False)
    net_quantity: Mapped[str] = mapped_column(Text, nullable=False)
    unit_cost: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[str] = mapped_column(Text, nullable=False)
    cost_source: Mapped[str] = mapped_column(Text, nullable=False)
    cost_entry_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('production_cost_entries.id'), nullable=True)


class ProductionSettlementDependency(Base):
    __tablename__ = 'production_settlement_dependencies'
    settlement_id: Mapped[int] = mapped_column(Integer, ForeignKey('production_cost_settlements.id'), primary_key=True)
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    source_id: Mapped[int] = mapped_column(Integer, primary_key=True)


class ProductionSettlementCharge(Base):
    __tablename__ = 'production_settlement_charges'
    settlement_id: Mapped[int] = mapped_column(Integer, ForeignKey('production_cost_settlements.id'), primary_key=True)
    entry_id: Mapped[int] = mapped_column(Integer, ForeignKey('production_cost_entries.id'), primary_key=True)


class StockMovement(Base):
    __tablename__ = 'stock_movements'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(Integer, ForeignKey('warehouses.id'), nullable=False)
    material_id: Mapped[int] = mapped_column(Integer, ForeignKey('materials.id'), nullable=False)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_line_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class InventoryCostInput(Base):
    __tablename__ = 'inventory_cost_inputs'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    movement_id: Mapped[int] = mapped_column(Integer, ForeignKey('stock_movements.id'), nullable=False)
    unit_cost: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class ReceiptOrderLink(Base):
    __tablename__ = 'receipt_order_links'
    receipt_line_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_order_line_id: Mapped[int] = mapped_column(Integer, ForeignKey('purchase_order_lines.id'), nullable=False)


class PurchaseOrderLine(Base):
    __tablename__ = 'purchase_order_lines'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(Integer, nullable=False)
    material_id: Mapped[int] = mapped_column(Integer, ForeignKey('materials.id'), nullable=False)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)
    unit_price: Mapped[str] = mapped_column(Text, nullable=False)


class SalesReturnLine(Base):
    __tablename__ = 'sales_return_lines'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sales_return_id: Mapped[int] = mapped_column(Integer, nullable=False)
    shipment_line_id: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)

class Customer(Base):
    __tablename__ = 'customers'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class SalesOrder(Base):
    __tablename__ = 'sales_orders'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(Integer, ForeignKey('customers.id'), nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    confirmed_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    cancelled_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    confirmed_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class SalesOrderLine(Base):
    __tablename__ = 'sales_order_lines'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sales_order_id: Mapped[int] = mapped_column(Integer, ForeignKey('sales_orders.id'), nullable=False)
    material_id: Mapped[int] = mapped_column(Integer, ForeignKey('materials.id'), nullable=False)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)
    unit_price: Mapped[str] = mapped_column(Text, nullable=False)


class Shipment(Base):
    __tablename__ = 'shipments'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sales_order_id: Mapped[int] = mapped_column(Integer, ForeignKey('sales_orders.id'), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(Integer, nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    posted_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    cancelled_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    posted_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class ShipmentLine(Base):
    __tablename__ = 'shipment_lines'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(Integer, ForeignKey('shipments.id'), nullable=False)
    sales_order_line_id: Mapped[int] = mapped_column(Integer, ForeignKey('sales_order_lines.id'), nullable=False)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)


class ShipmentReversal(Base):
    __tablename__ = 'shipment_reversals'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(Integer, ForeignKey('shipments.id'), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class SalesReturn(Base):
    __tablename__ = 'sales_returns'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(Integer, ForeignKey('shipments.id'), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    posted_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    cancelled_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    posted_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class SalesReturnReversal(Base):
    __tablename__ = 'sales_return_reversals'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sales_return_id: Mapped[int] = mapped_column(Integer, ForeignKey('sales_returns.id'), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class PurchaseOrder(Base):
    __tablename__ = 'purchase_orders'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int] = mapped_column(Integer, ForeignKey('suppliers.id'), nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    confirmed_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    cancelled_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    confirmed_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class Receipt(Base):
    __tablename__ = 'receipts'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int] = mapped_column(Integer, ForeignKey('suppliers.id'), nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    posted_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    posted_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class ReceiptLine(Base):
    __tablename__ = 'receipt_lines'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_id: Mapped[int] = mapped_column(Integer, ForeignKey('receipts.id'), nullable=False)
    material_id: Mapped[int] = mapped_column(Integer, ForeignKey('materials.id'), nullable=False)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)


class ReceiptReversal(Base):
    __tablename__ = 'receipt_reversals'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_id: Mapped[int] = mapped_column(Integer, ForeignKey('receipts.id'), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class PurchaseReturn(Base):
    __tablename__ = 'purchase_returns'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_id: Mapped[int] = mapped_column(Integer, ForeignKey('receipts.id'), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    posted_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    cancelled_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    posted_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class PurchaseReturnLine(Base):
    __tablename__ = 'purchase_return_lines'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_return_id: Mapped[int] = mapped_column(Integer, ForeignKey('purchase_returns.id'), nullable=False)
    receipt_line_id: Mapped[int] = mapped_column(Integer, ForeignKey('receipt_lines.id'), nullable=False)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)


class PurchaseReturnReversal(Base):
    __tablename__ = 'purchase_return_reversals'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_return_id: Mapped[int] = mapped_column(Integer, ForeignKey('purchase_returns.id'), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class PaymentRecord(Base):
    __tablename__ = 'payment_records'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    order_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    reverses_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('payment_records.id'), nullable=True)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))

class ReceiptWarehouse(Base):
    __tablename__ = "receipt_warehouses"
    receipt_id: Mapped[int] = mapped_column(Integer, ForeignKey("receipts.id"), primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(Integer, ForeignKey("warehouses.id"), nullable=False)


class Transfer(Base):
    __tablename__ = "transfers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_warehouse_id: Mapped[int] = mapped_column(Integer, ForeignKey("warehouses.id"), nullable=False)
    to_warehouse_id: Mapped[int] = mapped_column(Integer, ForeignKey("warehouses.id"), nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    posted_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    posted_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class TransferLine(Base):
    __tablename__ = "transfer_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transfer_id: Mapped[int] = mapped_column(Integer, ForeignKey("transfers.id"), nullable=False)
    material_id: Mapped[int] = mapped_column(Integer, ForeignKey("materials.id"), nullable=False)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)


class Stocktake(Base):
    __tablename__ = "stocktakes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(Integer, ForeignKey("warehouses.id"), nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    posted_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    cancelled_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    posted_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class StocktakeLine(Base):
    __tablename__ = "stocktake_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stocktake_id: Mapped[int] = mapped_column(Integer, ForeignKey("stocktakes.id"), nullable=False)
    material_id: Mapped[int] = mapped_column(Integer, ForeignKey("materials.id"), nullable=False)
    book_quantity: Mapped[str] = mapped_column(Text, nullable=False)
    counted_quantity: Mapped[str] = mapped_column(Text, nullable=False)
    movement_id: Mapped[int] = mapped_column(Integer, nullable=False)


class BomLine(Base):
    __tablename__ = "bom_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bom_id: Mapped[int] = mapped_column(Integer, ForeignKey("boms.id"), nullable=False)
    component_material_id: Mapped[int] = mapped_column(Integer, ForeignKey("materials.id"), nullable=False)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)


class StocktakeReversal(Base):
    __tablename__ = "stocktake_reversals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stocktake_id: Mapped[int] = mapped_column(Integer, ForeignKey("stocktakes.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class TransferReversal(Base):
    __tablename__ = "transfer_reversals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transfer_id: Mapped[int] = mapped_column(Integer, ForeignKey("transfers.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class PurchaseRequest(Base):
    __tablename__ = "purchase_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    submitted_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    cancelled_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    review_reason: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    submitted_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class PurchaseRequestLine(Base):
    __tablename__ = "purchase_request_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_request_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("purchase_requests.id"), nullable=False
    )
    material_id: Mapped[int] = mapped_column(Integer, ForeignKey("materials.id"), nullable=False)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)


class PurchaseOrderRequestLink(Base):
    __tablename__ = "purchase_order_request_links"
    purchase_order_line_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("purchase_order_lines.id"), primary_key=True
    )
    purchase_request_line_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("purchase_request_lines.id"), nullable=False
    )


class PurchaseGoodsReceipt(Base):
    __tablename__ = "purchase_goods_receipts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(Integer, ForeignKey("purchase_orders.id"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(Integer, ForeignKey("warehouses.id"), nullable=False)
    inbound_receipt_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("receipts.id"), nullable=True)
    reference: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    confirmed_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    cancelled_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    confirmed_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class PurchaseGoodsReceiptLine(Base):
    __tablename__ = "purchase_goods_receipt_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    goods_receipt_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("purchase_goods_receipts.id"), nullable=False
    )
    purchase_order_line_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("purchase_order_lines.id"), nullable=False
    )
    accepted_quantity: Mapped[str] = mapped_column(Text, nullable=False)
    rejected_quantity: Mapped[str] = mapped_column(Text, nullable=False)
    rejection_reason: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))


class WarehouseInbound(Base):
    __tablename__ = "warehouse_inbounds"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(Integer, ForeignKey("warehouses.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    posted_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    cancelled_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    posted_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class WarehouseInboundLine(Base):
    __tablename__ = "warehouse_inbound_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inbound_id: Mapped[int] = mapped_column(Integer, ForeignKey("warehouse_inbounds.id"), nullable=False)
    material_id: Mapped[int] = mapped_column(Integer, ForeignKey("materials.id"), nullable=False)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)


class WarehouseInboundReversal(Base):
    __tablename__ = "warehouse_inbound_reversals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inbound_id: Mapped[int] = mapped_column(Integer, ForeignKey("warehouse_inbounds.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class WarehouseOutbound(Base):
    __tablename__ = "warehouse_outbounds"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(Integer, ForeignKey("warehouses.id"), nullable=False)
    source_kind: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'other'"))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    posted_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    cancelled_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    posted_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    purchase_return_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("purchase_returns.id"), nullable=True
    )


class WarehouseOutboundLine(Base):
    __tablename__ = "warehouse_outbound_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    outbound_id: Mapped[int] = mapped_column(Integer, ForeignKey("warehouse_outbounds.id"), nullable=False)
    material_id: Mapped[int] = mapped_column(Integer, ForeignKey("materials.id"), nullable=False)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)


class WarehouseOutboundReversal(Base):
    __tablename__ = "warehouse_outbound_reversals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    outbound_id: Mapped[int] = mapped_column(Integer, ForeignKey("warehouse_outbounds.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class StockAdjustment(Base):
    __tablename__ = "stock_adjustments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(Integer, ForeignKey("warehouses.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    submitted_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    posted_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    cancelled_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    review_reason: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    submitted_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class StockAdjustmentLine(Base):
    __tablename__ = "stock_adjustment_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    adjustment_id: Mapped[int] = mapped_column(Integer, ForeignKey("stock_adjustments.id"), nullable=False)
    material_id: Mapped[int] = mapped_column(Integer, ForeignKey("materials.id"), nullable=False)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)


class StockAdjustmentReversal(Base):
    __tablename__ = "stock_adjustment_reversals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    adjustment_id: Mapped[int] = mapped_column(Integer, ForeignKey("stock_adjustments.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


# 客户归属与订单负责商务独立保存，代办或转交客户不会改写历史订单权限。
class CustomerProfile(Base):
    __tablename__ = 'customer_profiles'
    customer_id: Mapped[int] = mapped_column(ForeignKey('customers.id'), primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    contact_name: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    phone: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    address: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('1'))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('1'))


class SalesOrderOwner(Base):
    __tablename__ = 'sales_order_owners'
    order_id: Mapped[int] = mapped_column(ForeignKey('sales_orders.id'), primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('1'))


class CustomerChange(Base):
    __tablename__ = 'customer_changes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey('customers.id'), nullable=False)
    order_id: Mapped[int | None] = mapped_column(ForeignKey('sales_orders.id'))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))

# 扩展表保留原业务单据结构，税价与核算维度按保存时的值留存。
class TradeLineTerms(Base):
    __tablename__ = 'trade_line_terms'
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    line_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quoted_price: Mapped[str] = mapped_column(Text, nullable=False)
    tax_rate: Mapped[str] = mapped_column(Text, nullable=False)
    discount_rate: Mapped[str] = mapped_column(Text, nullable=False)
    includes_tax: Mapped[int] = mapped_column(Integer, nullable=False)


class JournalAuxiliary(Base):
    __tablename__ = 'journal_auxiliaries'
    line_id: Mapped[int] = mapped_column(ForeignKey('journal_lines.id', ondelete='CASCADE'), primary_key=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey('customers.id'))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey('suppliers.id'))
    department: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    project: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    labels_json: Mapped[str] = mapped_column(Text, nullable=False)


class PartyOpening(Base):
    __tablename__ = 'party_openings'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    party_id: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_date: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    ledger_account_id: Mapped[int] = mapped_column(ForeignKey('ledger_accounts.id'), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class PartyOpeningPayment(Base):
    __tablename__ = 'party_opening_payments'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opening_id: Mapped[int] = mapped_column(ForeignKey('party_openings.id'), nullable=False)
    amount: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class BankStatement(Base):
    __tablename__ = 'bank_statements'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bank_account: Mapped[str] = mapped_column(Text, nullable=False)
    statement_date: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class BankMatch(Base):
    __tablename__ = 'bank_matches'
    statement_id: Mapped[int] = mapped_column(ForeignKey('bank_statements.id'), primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey('payment_records.id'), nullable=False, unique=True)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class FinanceToolAudit(Base):
    __tablename__ = 'finance_tool_audits'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    record_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
