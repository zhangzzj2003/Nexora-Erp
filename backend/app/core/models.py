"""业务 ORM 模型；金额保留文本精度，库结构由版本迁移维护。"""

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CrmContact(Base):
    __tablename__ = 'crm_contacts'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(Integer, ForeignKey('customers.id'), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    job_title: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class CrmOpportunity(Base):
    __tablename__ = 'crm_opportunities'
    __table_args__ = (CheckConstraint('probability_percent BETWEEN 0 AND 100', name='crm_opportunity_probability_range'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(Integer, ForeignKey('customers.id'), nullable=False)
    contact_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('crm_contacts.id'))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_amount: Mapped[str] = mapped_column(Text, nullable=False)
    probability_percent: Mapped[int | None] = mapped_column(Integer)
    expected_close_date: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class CrmActivity(Base):
    __tablename__ = 'crm_activities'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(Integer, ForeignKey('customers.id'), nullable=False)
    contact_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('crm_contacts.id'))
    opportunity_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('crm_opportunities.id'))
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    due_date: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    closed_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'))
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    closed_at: Mapped[str | None] = mapped_column(Text)


class CrmQuote(Base):
    __tablename__ = 'crm_quotes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(Integer, ForeignKey('crm_opportunities.id'), nullable=False)
    customer_id: Mapped[int] = mapped_column(Integer, ForeignKey('customers.id'), nullable=False)
    contact_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('crm_contacts.id'))
    reference: Mapped[str] = mapped_column(Text, nullable=False)
    valid_until: Mapped[str] = mapped_column(Text, nullable=False)
    terms: Mapped[str] = mapped_column(Text, nullable=False)
    party_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    submitted_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'))
    reviewed_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'))
    converted_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'))
    sales_order_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('sales_orders.id'))
    acceptance_reference: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    submitted_at: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[str | None] = mapped_column(Text)
    converted_at: Mapped[str | None] = mapped_column(Text)


class CrmQuoteLine(Base):
    __tablename__ = 'crm_quote_lines'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quote_id: Mapped[int] = mapped_column(Integer, ForeignKey('crm_quotes.id'), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    material_id: Mapped[int] = mapped_column(Integer, ForeignKey('materials.id'), nullable=False)
    sku: Mapped[str] = mapped_column(Text, nullable=False)
    material_name: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)
    unit_price: Mapped[str] = mapped_column(Text, nullable=False)


class CrmChange(Base):
    __tablename__ = 'crm_changes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_kind: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class MrpPolicy(Base):
    __tablename__ = 'mrp_policies'
    material_id: Mapped[int] = mapped_column(Integer, ForeignKey('materials.id'), primary_key=True)
    supply_mode: Mapped[str] = mapped_column(Text, nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
    safety_stock: Mapped[str] = mapped_column(Text, nullable=False)
    minimum_quantity: Mapped[str] = mapped_column(Text, nullable=False)
    multiple_quantity: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    changed_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class MrpPolicyChange(Base):
    __tablename__ = 'mrp_policy_changes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    material_id: Mapped[int] = mapped_column(Integer, ForeignKey('materials.id'), nullable=False)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class MrpPlan(Base):
    __tablename__ = 'mrp_plans'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference: Mapped[str] = mapped_column(Text, nullable=False)
    input_json: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    submitted_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'))
    reviewed_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'))
    cancelled_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'))
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    submitted_at: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[str | None] = mapped_column(Text)


class MrpPlanChange(Base):
    __tablename__ = 'mrp_plan_changes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(Integer, ForeignKey('mrp_plans.id'), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class MrpConversion(Base):
    __tablename__ = 'mrp_conversions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(Integer, ForeignKey('mrp_plans.id'), nullable=False)
    suggestion_key: Mapped[str] = mapped_column(Text, nullable=False)
    purchase_request_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('purchase_requests.id'))
    work_order_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('work_orders.id'))
    due_date: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class AuxiliaryItem(Base):
    __tablename__ = 'auxiliary_items'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class AuxiliaryItemChange(Base):
    __tablename__ = 'auxiliary_item_changes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey('auxiliary_items.id'), nullable=False)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class AuxiliaryPolicy(Base):
    __tablename__ = 'auxiliary_policies'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey('ledger_accounts.id'), nullable=False, unique=True)
    start_date: Mapped[str] = mapped_column(Text, nullable=False)
    required_kinds_json: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class AuxiliaryPolicyChange(Base):
    __tablename__ = 'auxiliary_policy_changes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey('ledger_accounts.id'), nullable=False)
    before_json: Mapped[str] = mapped_column(Text, nullable=False)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class AuxiliaryAssignment(Base):
    __tablename__ = 'auxiliary_assignments'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    journal_line_id: Mapped[int | None] = mapped_column(ForeignKey('journal_lines.id', ondelete='CASCADE'))
    opening_line_id: Mapped[int | None] = mapped_column(ForeignKey('opening_balance_lines.id', ondelete='CASCADE'))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey('customers.id'))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey('suppliers.id'))
    item_id: Mapped[int | None] = mapped_column(ForeignKey('auxiliary_items.id'))
    code_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    name_snapshot: Mapped[str] = mapped_column(Text, nullable=False)


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


class FinancialStatementPolicy(Base):
    __tablename__ = 'financial_statement_policies'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    configuration_json: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class FinancialStatementPolicyChange(Base):
    __tablename__ = 'financial_statement_policy_changes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    before_json: Mapped[str] = mapped_column(Text, nullable=False)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class FinancialStatement(Base):
    __tablename__ = 'financial_statements'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_date: Mapped[str] = mapped_column(Text, nullable=False)
    to_date: Mapped[str] = mapped_column(Text, nullable=False)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
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


class SubledgerOpening(Base):
    __tablename__ = 'subledger_openings'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    opening_balance_id: Mapped[int] = mapped_column(ForeignKey('opening_balances.id'), nullable=False)
    opening_version: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_date: Mapped[str] = mapped_column(Text, nullable=False)
    control_accounts_json: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str] = mapped_column(Text, nullable=False)
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


class SubledgerOpeningLine(Base):
    __tablename__ = 'subledger_opening_lines'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opening_id: Mapped[int] = mapped_column(ForeignKey('subledger_openings.id'), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey('ledger_accounts.id'), nullable=False)
    account_code: Mapped[str] = mapped_column(Text, nullable=False)
    account_name: Mapped[str] = mapped_column(Text, nullable=False)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey('customers.id'))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey('suppliers.id'))
    document_reference: Mapped[str] = mapped_column(Text, nullable=False)
    document_date: Mapped[str] = mapped_column(Text, nullable=False)
    debit: Mapped[str] = mapped_column(Text, nullable=False)
    credit: Mapped[str] = mapped_column(Text, nullable=False)
    auxiliary_json: Mapped[str] = mapped_column(Text, nullable=False)


class SubledgerOpeningChange(Base):
    __tablename__ = 'subledger_opening_changes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opening_id: Mapped[int] = mapped_column(ForeignKey('subledger_openings.id'), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class SubledgerPayment(Base):
    __tablename__ = 'subledger_payments'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opening_line_id: Mapped[int] = mapped_column(ForeignKey('subledger_opening_lines.id'), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    reverses_id: Mapped[int | None] = mapped_column(ForeignKey('subledger_payments.id'), unique=True)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
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

    # 旧档案不猜测分类或参数，迁移后逐步补齐；版本用于防止编辑覆盖。
    category_code: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    specification: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    package: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    brand: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    manufacturer_part_number: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    electrical_value: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    tolerance: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    rated_voltage: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    rated_power: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    temperature_range: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    compliance: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    notes: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('1'))


class MaterialCodeSequence(Base):
    # 永久保留各子类流水，删除档案不会重置编号。
    __tablename__ = 'material_code_sequences'
    prefix: Mapped[str] = mapped_column(Text, primary_key=True)
    last_number: Mapped[int] = mapped_column(Integer, nullable=False)


class MaterialChange(Base):
    __tablename__ = 'material_changes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    material_id: Mapped[int] = mapped_column(Integer, nullable=False)
    sku: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
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
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('1'))
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class SupplierChange(Base):
    __tablename__ = 'supplier_changes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
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
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('1'))
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class WarehouseChange(Base):
    __tablename__ = 'warehouse_changes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
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


class MaterialIssueReversal(Base):
    __tablename__ = 'material_issue_reversals'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    material_issue_id: Mapped[int] = mapped_column(Integer, ForeignKey('material_issues.id'), nullable=False, unique=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


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


class MaterialReturnReversal(Base):
    __tablename__ = 'material_return_reversals'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    material_return_id: Mapped[int] = mapped_column(Integer, ForeignKey('material_returns.id'), nullable=False, unique=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


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
    rework_amount: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'0.00'"))
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


class QualityDisposition(Base):
    __tablename__ = 'quality_dispositions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    completion_id: Mapped[int] = mapped_column(Integer, ForeignKey('production_completions.id'), nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)
    loss_treatment: Mapped[str] = mapped_column(Text, nullable=False)
    defect: Mapped[str] = mapped_column(Text, nullable=False)
    action_note: Mapped[str] = mapped_column(Text, nullable=False)
    warehouse_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('warehouses.id'), nullable=True)
    materials_json: Mapped[str] = mapped_column(Text, nullable=False)
    source_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    rework_order_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('work_orders.id'), nullable=True, unique=True)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    submitted_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    posted_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    reversed_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    submitted_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    reversed_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class QualityDispositionChange(Base):
    __tablename__ = 'quality_disposition_changes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    disposition_id: Mapped[int] = mapped_column(Integer, ForeignKey('quality_dispositions.id'), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    before_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class QualityCostAllocation(Base):
    __tablename__ = 'quality_cost_allocations'
    settlement_id: Mapped[int] = mapped_column(Integer, ForeignKey('production_cost_settlements.id'), primary_key=True)
    disposition_id: Mapped[int] = mapped_column(Integer, ForeignKey('quality_dispositions.id'), primary_key=True)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    loss_treatment: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class ProductionReworkSource(Base):
    __tablename__ = 'production_rework_sources'
    settlement_id: Mapped[int] = mapped_column(Integer, ForeignKey('production_cost_settlements.id'), primary_key=True)
    disposition_id: Mapped[int] = mapped_column(Integer, ForeignKey('quality_dispositions.id'), primary_key=True)
    origin_settlement_id: Mapped[int] = mapped_column(Integer, ForeignKey('production_cost_settlements.id'), nullable=False)
    amount: Mapped[str] = mapped_column(Text, nullable=False)


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


class PhysicalLot(Base):
    __tablename__ = 'physical_lots'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    material_id: Mapped[int] = mapped_column(Integer, ForeignKey('materials.id'), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)
    supplier_lot: Mapped[str | None] = mapped_column(Text)
    manufactured_on: Mapped[str | None] = mapped_column(Text)
    expires_on: Mapped[str | None] = mapped_column(Text)
    origin_movement_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('stock_movements.id'))
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'))
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class PhysicalLotOpening(Base):
    __tablename__ = 'physical_lot_openings'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lot_id: Mapped[int] = mapped_column(Integer, ForeignKey('physical_lots.id'), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(Integer, ForeignKey('warehouses.id'), nullable=False)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)
    checkpoint_movement_id: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class PhysicalLotAllocation(Base):
    __tablename__ = 'physical_lot_allocations'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lot_id: Mapped[int] = mapped_column(Integer, ForeignKey('physical_lots.id'), nullable=False)
    movement_id: Mapped[int] = mapped_column(Integer, ForeignKey('stock_movements.id'), nullable=False)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)
    original_allocation_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('physical_lot_allocations.id'))


class PhysicalLotReclassification(Base):
    __tablename__ = 'physical_lot_reclassifications'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    legacy_lot_id: Mapped[int] = mapped_column(Integer, ForeignKey('physical_lots.id'), nullable=False)
    verified_lot_id: Mapped[int] = mapped_column(Integer, ForeignKey('physical_lots.id'), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(Integer, ForeignKey('warehouses.id'), nullable=False)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    original_reclassification_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('physical_lot_reclassifications.id'))
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class PhysicalLotMovementCheckpoint(Base):
    __tablename__ = 'physical_lot_movement_checkpoints'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    movement_id: Mapped[int] = mapped_column(Integer, nullable=False)
    basis: Mapped[str] = mapped_column(Text, nullable=False)


class PhysicalLotMovementEvidence(Base):
    __tablename__ = 'physical_lot_movement_evidence'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    movement_id: Mapped[int] = mapped_column(Integer, ForeignKey('stock_movements.id'), nullable=False)
    lot_id: Mapped[int] = mapped_column(Integer, ForeignKey('physical_lots.id'), nullable=False)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    original_evidence_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('physical_lot_movement_evidence.id'))
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class PhysicalLotEvidencePair(Base):
    __tablename__ = 'physical_lot_evidence_pairs'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inbound_movement_id: Mapped[int] = mapped_column(Integer, ForeignKey('stock_movements.id'), nullable=False)
    outbound_movement_id: Mapped[int] = mapped_column(Integer, ForeignKey('stock_movements.id'), nullable=False)
    inbound_evidence_id: Mapped[int] = mapped_column(Integer, ForeignKey('physical_lot_movement_evidence.id'), nullable=False)
    outbound_evidence_id: Mapped[int] = mapped_column(Integer, ForeignKey('physical_lot_movement_evidence.id'), nullable=False)
    lot_id: Mapped[int] = mapped_column(Integer, ForeignKey('physical_lots.id'), nullable=False)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    original_pair_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('physical_lot_evidence_pairs.id'))
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class PhysicalLotEvidenceGroup(Base):
    __tablename__ = 'physical_lot_evidence_groups'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lot_id: Mapped[int] = mapped_column(Integer, ForeignKey('physical_lots.id'), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(Integer, ForeignKey('warehouses.id'), nullable=False)
    material_id: Mapped[int] = mapped_column(Integer, ForeignKey('materials.id'), nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    original_group_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('physical_lot_evidence_groups.id'))
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class PhysicalLotEvidenceGroupPair(Base):
    __tablename__ = 'physical_lot_evidence_group_pairs'
    group_id: Mapped[int] = mapped_column(Integer, ForeignKey('physical_lot_evidence_groups.id'), primary_key=True)
    pair_id: Mapped[int] = mapped_column(Integer, ForeignKey('physical_lot_evidence_pairs.id'), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


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

class AfterSalesCase(Base):
    __tablename__ = "after_sales_cases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    shipment_line_id: Mapped[int] = mapped_column(Integer, ForeignKey("shipment_lines.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)
    complaint: Mapped[str] = mapped_column(Text, nullable=False)
    solution: Mapped[str] = mapped_column(Text, nullable=False)
    source_json: Mapped[str] = mapped_column(Text, nullable=False)
    charge_mode: Mapped[str] = mapped_column(Text, nullable=False)
    fee_amount: Mapped[str] = mapped_column(Text, nullable=False)
    customer_acceptance: Mapped[str] = mapped_column(Text, nullable=False)
    warehouse_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("warehouses.id"))
    replacement_material_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("materials.id"))
    replacement_quantity: Mapped[str | None] = mapped_column(Text)
    replacement_unit_price: Mapped[str | None] = mapped_column(Text)
    parts_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    sales_return_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sales_returns.id"), unique=True)
    replacement_order_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sales_orders.id"), unique=True)
    parts_outbound_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("warehouse_outbounds.id"), unique=True)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    submitted_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    reviewed_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    closed_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    reversed_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    submitted_at: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[str | None] = mapped_column(Text)
    reversed_at: Mapped[str | None] = mapped_column(Text)


class AfterSalesChange(Base):
    __tablename__ = "after_sales_changes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(Integer, ForeignKey("after_sales_cases.id"), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class AfterSalesCustody(Base):
    __tablename__ = "after_sales_custody"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(Integer, ForeignKey("after_sales_cases.id"), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class AfterSalesLabor(Base):
    __tablename__ = "after_sales_labor"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(Integer, ForeignKey("after_sales_cases.id"), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    hours: Mapped[str] = mapped_column(Text, nullable=False)
    original_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("after_sales_labor.id"), unique=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class Customer(Base):
    __tablename__ = 'customers'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('1'))
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class CustomerOwnerChange(Base):
    __tablename__ = 'customer_owner_changes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(Integer, ForeignKey('customers.id'), nullable=False)
    before_owner_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    after_owner_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
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




class EquipmentAsset(Base):
    __tablename__ = 'equipment_assets'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    serial_number: Mapped[str | None] = mapped_column(Text, unique=True)
    location: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))

class MaintenancePlan(Base):
    __tablename__ = 'maintenance_plans'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    equipment_id: Mapped[int] = mapped_column(Integer, ForeignKey('equipment_assets.id'), nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False)
    next_due: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))

class EquipmentMeterReading(Base):
    __tablename__ = 'equipment_meter_readings'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    equipment_id: Mapped[int] = mapped_column(Integer, ForeignKey('equipment_assets.id'), nullable=False)
    hours: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    previous_reading_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('equipment_meter_readings.id'))
    correction: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    recorded_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))

class MaintenanceHourPlan(Base):
    __tablename__ = 'maintenance_hour_plans'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    equipment_id: Mapped[int] = mapped_column(Integer, ForeignKey('equipment_assets.id'), nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    interval_hours: Mapped[str] = mapped_column(Text, nullable=False)
    next_due_hours: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))

class MaintenanceHourPlanChange(Base):
    __tablename__ = 'maintenance_hour_plan_changes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(Integer, ForeignKey('maintenance_hour_plans.id'), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))

class MaintenanceJob(Base):
    __tablename__ = 'maintenance_jobs'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    equipment_id: Mapped[int] = mapped_column(Integer, ForeignKey('equipment_assets.id'), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    plan_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('maintenance_plans.id'))
    plan_version: Mapped[int | None] = mapped_column(Integer)
    plan_due_date: Mapped[str | None] = mapped_column(Text)
    hour_plan_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('maintenance_hour_plans.id'))
    plan_due_hours: Mapped[str | None] = mapped_column(Text)
    plan_meter_reading_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('equipment_meter_readings.id'))
    work_order_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('work_orders.id'))
    assigned_to: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    request_note: Mapped[str] = mapped_column(Text, nullable=False)
    equipment_json: Mapped[str] = mapped_column(Text, nullable=False)
    work_order_json: Mapped[str] = mapped_column(Text, nullable=False)
    parts_json: Mapped[str] = mapped_column(Text, nullable=False)
    warehouse_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('warehouses.id'))
    parts_outbound_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('warehouse_outbounds.id'), unique=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    solution: Mapped[str] = mapped_column(Text, nullable=False)
    labor_hours: Mapped[str | None] = mapped_column(Text)
    service_amount: Mapped[str | None] = mapped_column(Text)
    plan_roll_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    reviewed_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'))
    reported_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'))
    accepted_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'))
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    started_at: Mapped[str | None] = mapped_column(Text)
    reported_at: Mapped[str | None] = mapped_column(Text)
    accepted_at: Mapped[str | None] = mapped_column(Text)

class MaintenanceDowntime(Base):
    __tablename__ = 'maintenance_downtimes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    equipment_id: Mapped[int] = mapped_column(Integer, ForeignKey('equipment_assets.id'), nullable=False)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey('maintenance_jobs.id'), nullable=False, unique=True)
    started_at: Mapped[str] = mapped_column(Text, nullable=False)
    ended_at: Mapped[str | None] = mapped_column(Text)
    close_reason: Mapped[str] = mapped_column(Text, nullable=False)
    started_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    ended_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'))

class MaintenanceChange(Base):
    __tablename__ = 'maintenance_changes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class StockAdjustmentReversal(Base):
    __tablename__ = "stock_adjustment_reversals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    adjustment_id: Mapped[int] = mapped_column(Integer, ForeignKey("stock_adjustments.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class InventoryWarningRule(Base):
    __tablename__ = 'inventory_warning_rules'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(Integer, ForeignKey('warehouses.id'), nullable=False)
    material_id: Mapped[int] = mapped_column(Integer, ForeignKey('materials.id'), nullable=False)
    threshold: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class InventoryWarningChange(Base):
    __tablename__ = 'inventory_warning_changes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int] = mapped_column(Integer, ForeignKey('inventory_warning_rules.id'), nullable=False)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class InventoryWarningObservation(Base):
    __tablename__ = 'inventory_warning_observations'
    rule_id: Mapped[int] = mapped_column(Integer, ForeignKey('inventory_warning_rules.id'), primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class InventoryWarningEvent(Base):
    __tablename__ = 'inventory_warning_events'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int] = mapped_column(Integer, ForeignKey('inventory_warning_rules.id'), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(Integer, ForeignKey('warehouses.id'), nullable=False)
    material_id: Mapped[int] = mapped_column(Integer, ForeignKey('materials.id'), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[str] = mapped_column(Text, nullable=False)
    threshold: Mapped[str] = mapped_column(Text, nullable=False)
    shortage: Mapped[str] = mapped_column(Text, nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    warehouse_code: Mapped[str] = mapped_column(Text, nullable=False)
    warehouse_name: Mapped[str] = mapped_column(Text, nullable=False)
    sku: Mapped[str] = mapped_column(Text, nullable=False)
    material_name: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
