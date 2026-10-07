"""旧库夹具只回退待验证版本之后的结构，不让新版表混入旧库。"""

import pytest


@pytest.fixture
def remove_after_sales_labor_schema():
    def remove(db):
        db.execute('DROP TABLE IF EXISTS after_sales_labor_costs')
        db.execute("DELETE FROM role_permissions WHERE permission_code='after_sales.cost'")
        db.execute("DELETE FROM permissions WHERE code='after_sales.cost'")
        db.execute('DROP TABLE IF EXISTS equipment_attachment_reversals')
        db.execute('DROP TABLE IF EXISTS equipment_attachments')
        db.execute("DELETE FROM role_permissions WHERE permission_code='equipment.attachment'")
        db.execute("DELETE FROM permissions WHERE code='equipment.attachment'")
        db.execute('DROP TABLE IF EXISTS crm_record_attachment_reversals')
        db.execute('DROP TABLE IF EXISTS crm_record_attachments')
        db.execute("DELETE FROM role_permissions WHERE permission_code='crm.attachment'")
        db.execute("DELETE FROM permissions WHERE code='crm.attachment'")
        db.execute('DROP TABLE IF EXISTS crm_quote_attachment_reversals')
        db.execute('DROP TABLE IF EXISTS crm_quote_attachments')
        db.execute("DELETE FROM role_permissions WHERE permission_code='crm_quote.attachment'")
        db.execute("DELETE FROM permissions WHERE code='crm_quote.attachment'")
        db.execute('DROP TABLE IF EXISTS after_sales_attachment_reversals')
        db.execute('DROP TABLE IF EXISTS after_sales_attachments')
        db.execute("DELETE FROM role_permissions WHERE permission_code='after_sales.attachment'")
        db.execute("DELETE FROM permissions WHERE code='after_sales.attachment'")
        db.execute('DROP TABLE IF EXISTS inventory_warning_events')
        db.execute('DROP TABLE IF EXISTS inventory_warning_observations')
        db.execute('DROP TABLE IF EXISTS material_return_reversals')
        db.execute("DELETE FROM role_permissions WHERE permission_code='material_return.reverse'")
        db.execute("DELETE FROM permissions WHERE code='material_return.reverse'")
        db.execute('DROP TABLE IF EXISTS material_issue_reversals')
        db.execute("DELETE FROM role_permissions WHERE permission_code='material_issue.reverse'")
        db.execute("DELETE FROM permissions WHERE code='material_issue.reverse'")
        db.execute('DROP TABLE IF EXISTS after_sales_labor')
        db.execute("DELETE FROM role_permissions WHERE permission_code='after_sales.labor'")
        db.execute("DELETE FROM permissions WHERE code='after_sales.labor'")
    return remove


@pytest.fixture
def remove_equipment_hour_schema(remove_after_sales_labor_schema):
    def remove(db):
        remove_after_sales_labor_schema(db)
        # 旧库升级夹具必须撤掉新版小时结构，才能真实重放第 63 版迁移。
        db.execute('DROP INDEX IF EXISTS maintenance_hour_occurrence')
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'maintenance_jobs' in tables:
            columns = {row[1] for row in db.execute('PRAGMA table_info(maintenance_jobs)')}
            for field in ('plan_meter_reading_id', 'plan_due_hours', 'hour_plan_id'):
                if field in columns:
                    db.execute(f'ALTER TABLE maintenance_jobs DROP COLUMN {field}')
        for table in ('maintenance_hour_plan_changes', 'maintenance_hour_plans', 'equipment_meter_readings'):
            db.execute(f'DROP TABLE IF EXISTS {table}')
        db.execute("DELETE FROM role_permissions WHERE permission_code='equipment.meter'")
        db.execute("DELETE FROM permissions WHERE code='equipment.meter'")
    return remove


@pytest.fixture
def remove_physical_lot_schema(remove_equipment_hour_schema):
    def remove(db):
        remove_equipment_hour_schema(db)
        db.execute('DROP TABLE IF EXISTS customer_owner_changes')
        db.execute('DROP INDEX IF EXISTS customer_owner_lookup')
        fields = {row[1] for row in db.execute('PRAGMA table_info(customers)')}
        if 'owner_id' in fields:
            db.execute('ALTER TABLE customers DROP COLUMN owner_id')
        if 'version' in fields:
            db.execute('ALTER TABLE customers DROP COLUMN version')
        db.execute("DELETE FROM role_permissions WHERE permission_code='customer.assign'")
        db.execute("DELETE FROM permissions WHERE code='customer.assign'")
        db.execute("DELETE FROM role_permissions WHERE permission_code='customer.view_all'")
        db.execute("DELETE FROM permissions WHERE code='customer.view_all'")
        db.execute('DROP TABLE IF EXISTS physical_lot_evidence_group_pairs')
        db.execute('DROP TABLE IF EXISTS physical_lot_evidence_groups')
        db.execute('DROP TABLE IF EXISTS physical_lot_evidence_pairs')
        db.execute('DROP TABLE IF EXISTS physical_lot_movement_evidence')
        db.execute('DROP TABLE IF EXISTS physical_lot_movement_checkpoints')
        db.execute("DELETE FROM role_permissions WHERE permission_code='physical_lot.movement_evidence'")
        db.execute("DELETE FROM permissions WHERE code='physical_lot.movement_evidence'")
        db.execute('DROP TABLE IF EXISTS physical_lot_reclassifications')
        db.execute("DELETE FROM role_permissions WHERE permission_code='physical_lot.reclassify'")
        db.execute("DELETE FROM permissions WHERE code='physical_lot.reclassify'")
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='permission_groups'").fetchone():
            db.execute("DELETE FROM permission_groups WHERE code='warehouse.physical_lots'")
        for table in ('physical_lot_allocations', 'physical_lot_openings', 'physical_lots'):
            db.execute(f'DROP TABLE IF EXISTS {table}')
    return remove


@pytest.fixture
def remove_inventory_warning_schema(remove_physical_lot_schema):
    def remove(db):
        remove_physical_lot_schema(db)
        for table in ('inventory_warning_changes','inventory_warning_rules'):
            db.execute(f'DROP TABLE IF EXISTS {table}')
        db.execute("DELETE FROM role_permissions WHERE permission_code='inventory_warning.manage'")
        db.execute("DELETE FROM permissions WHERE code='inventory_warning.manage'")
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='permission_groups'").fetchone():
            db.execute("DELETE FROM permission_groups WHERE code='warehouse.warnings'")
    return remove



@pytest.fixture
def remove_material_schema(remove_inventory_warning_schema):
    def remove(db):
        remove_inventory_warning_schema(db)
        db.execute('DROP TABLE IF EXISTS material_changes')
        db.execute('DROP TABLE IF EXISTS material_code_sequences')
        from app.catalog.material_rules import DETAIL_FIELDS
        existing = {row[1] for row in db.execute('PRAGMA table_info(materials)')}
        for field in (*DETAIL_FIELDS, 'version'):
            if field in existing:
                db.execute(f'ALTER TABLE materials DROP COLUMN {field}')
    return remove


@pytest.fixture
def remove_equipment_schema(remove_material_schema):
    def remove(db):
        remove_material_schema(db)
        for table in ('maintenance_changes','maintenance_downtimes','maintenance_jobs','maintenance_hour_plan_changes','maintenance_hour_plans',
                      'equipment_meter_readings','maintenance_plans','equipment_assets'):
            db.execute(f'DROP TABLE IF EXISTS {table}')
        for action in ('view','manage','create','submit','review','execute','accept','cancel','reverse','meter','attachment'):
            code = 'equipment.' + action
            db.execute('DELETE FROM role_permissions WHERE permission_code=?', (code,))
            db.execute('DELETE FROM permissions WHERE code=?', (code,))
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='permission_groups'").fetchone():
            db.execute("DELETE FROM permission_groups WHERE code='production.equipment'")
    return remove


@pytest.fixture
def remove_after_sales_schema(remove_equipment_schema):
    def remove(db):
        remove_equipment_schema(db)
        for table in ('after_sales_custody','after_sales_changes','after_sales_cases'):
            db.execute(f'DROP TABLE IF EXISTS {table}')
        for action in ('view','create','submit','review','process','receive','inspect','close','cancel','reverse'):
            code='after_sales.'+action
            db.execute('DELETE FROM role_permissions WHERE permission_code=?',(code,))
            db.execute('DELETE FROM permissions WHERE code=?',(code,))
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='permission_groups'").fetchone():
            db.execute("DELETE FROM permission_groups WHERE code='sales.after_sales'")
    return remove


@pytest.fixture
def remove_quality_schema(remove_after_sales_schema):
    def remove(db):
        remove_after_sales_schema(db)
        for table in ('production_rework_sources','quality_cost_allocations','quality_disposition_changes','quality_dispositions'):
            db.execute(f'DROP TABLE IF EXISTS {table}')
        if any(row[1] == 'rework_amount' for row in db.execute('PRAGMA table_info(production_cost_settlements)')):
            db.execute('ALTER TABLE production_cost_settlements DROP COLUMN rework_amount')
        for action in ('view','create','submit','review','post','cancel','reverse'):
            code = 'quality.' + action
            db.execute('DELETE FROM role_permissions WHERE permission_code=?', (code,))
            db.execute('DELETE FROM permissions WHERE code=?', (code,))
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='permission_groups'").fetchone():
            db.execute("DELETE FROM permission_groups WHERE code='production.quality'")
    return remove


@pytest.fixture
def remove_crm_schema(remove_quality_schema):
    def remove(db):
        remove_quality_schema(db)
        for table in ('crm_changes','crm_quote_lines','crm_quotes','crm_activities','crm_opportunities','crm_contacts'):
            db.execute(f'DROP TABLE IF EXISTS {table}')
        for code in ('crm.view','crm_contact.manage','crm_activity.manage','crm_opportunity.manage',
                     'crm_quote.create','crm_quote.submit','crm_quote.review','crm_quote.cancel','crm_quote.convert'):
            db.execute('DELETE FROM role_permissions WHERE permission_code=?', (code,))
            db.execute('DELETE FROM permissions WHERE code=?', (code,))
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='permission_groups'").fetchone():
            db.execute("DELETE FROM permission_groups WHERE code='sales.crm'")
    return remove


@pytest.fixture
def remove_mrp_schema(remove_crm_schema):
    def remove(db):
        remove_crm_schema(db)
        for table in ('mrp_conversions','mrp_plan_changes','mrp_plans','mrp_policy_changes','mrp_policies'):
            db.execute(f'DROP TABLE IF EXISTS {table}')
        for operation in ('view','configure','create','submit','review','cancel','convert'):
            code = 'mrp.' + operation
            db.execute('DELETE FROM role_permissions WHERE permission_code=?', (code,))
            db.execute('DELETE FROM permissions WHERE code=?', (code,))
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='permission_groups'").fetchone():
            db.execute("DELETE FROM permission_groups WHERE code='production.mrp'")
        db.execute("DELETE FROM role_permissions WHERE role_code='planner' AND permission_code LIKE 'purchase_request.%'")
    return remove


@pytest.fixture
def remove_subledger_schema(remove_mrp_schema):
    def remove(db):
        remove_mrp_schema(db)
        for table in ('subledger_payments', 'subledger_opening_changes', 'subledger_opening_lines', 'subledger_openings'):
            db.execute(f'DROP TABLE IF EXISTS {table}')
        for operation in ('view', 'create', 'submit', 'review', 'confirm', 'cancel', 'reverse'):
            code = 'subledger_opening.' + operation
            db.execute('DELETE FROM role_permissions WHERE permission_code=?', (code,))
            db.execute('DELETE FROM permissions WHERE code=?', (code,))
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='permission_groups'").fetchone():
            db.execute("DELETE FROM permission_groups WHERE code='finance.subledger_openings'")
    return remove


@pytest.fixture
def remove_auxiliary_schema(remove_subledger_schema):
    def remove(db):
        remove_subledger_schema(db)
        for table in ('auxiliary_assignments', 'auxiliary_policy_changes', 'auxiliary_policies', 'auxiliary_item_changes', 'auxiliary_items'):
            db.execute(f'DROP TABLE IF EXISTS {table}')
        for operation in ('view', 'configure', 'manage'):
            code = 'auxiliary.' + operation
            db.execute('DELETE FROM role_permissions WHERE permission_code=?', (code,))
            db.execute('DELETE FROM permissions WHERE code=?', (code,))
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='permission_groups'").fetchone():
            db.execute("DELETE FROM permission_groups WHERE code='finance.auxiliary'")
    return remove


@pytest.fixture
def remove_statement_schema(remove_auxiliary_schema):
    def remove(db):
        remove_auxiliary_schema(db)
        for table in ('financial_statements', 'financial_statement_policy_changes', 'financial_statement_policies'):
            db.execute(f'DROP TABLE IF EXISTS {table}')
        for operation in ('view', 'configure', 'archive'):
            code = 'financial_statement.' + operation
            db.execute('DELETE FROM role_permissions WHERE permission_code=?', (code,))
            db.execute('DELETE FROM permissions WHERE code=?', (code,))
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='permission_groups'").fetchone():
            db.execute("DELETE FROM permission_groups WHERE code='finance.statements'")
    return remove


@pytest.fixture
def remove_transfer_schema(remove_statement_schema):
    def remove(db):
        remove_statement_schema(db)
        for table in ('profit_transfers', 'profit_transfer_policy_changes', 'profit_transfer_policies'):
            db.execute(f'DROP TABLE IF EXISTS {table}')
        for operation in ('view', 'configure', 'generate'):
            code = 'profit_transfer.' + operation
            db.execute('DELETE FROM role_permissions WHERE permission_code=?', (code,))
            db.execute('DELETE FROM permissions WHERE code=?', (code,))
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='permission_groups'").fetchone():
            db.execute("DELETE FROM permission_groups WHERE code='finance.profit_transfers'")
    return remove


@pytest.fixture
def remove_closing_schema(remove_transfer_schema):
    def remove(db):
        remove_transfer_schema(db)
        for table in ('business_journal_sources', 'business_journal_policy_changes', 'business_journal_policies'):
            db.execute(f'DROP TABLE IF EXISTS {table}')
        for operation in ('view', 'configure', 'generate'):
            code = 'business_journal.' + operation
            db.execute('DELETE FROM role_permissions WHERE permission_code=?', (code,))
            db.execute('DELETE FROM permissions WHERE code=?', (code,))
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='permission_groups'").fetchone():
            db.execute("DELETE FROM permission_groups WHERE code='finance.business_journals'")
        db.execute('DROP TABLE IF EXISTS period_closings')
        for operation in ('closing_view', 'close', 'reopen'):
            code = 'accounting_period.' + operation
            db.execute('DELETE FROM role_permissions WHERE permission_code=?', (code,))
            db.execute('DELETE FROM permissions WHERE code=?', (code,))
    return remove


@pytest.fixture
def remove_journal_schema(remove_closing_schema):
    def remove(db):
        remove_closing_schema(db)
        for table in ('opening_balance_changes','opening_balance_lines','opening_balances'):
            db.execute(f'DROP TABLE IF EXISTS {table}')
        for operation in ('view','create','submit','review','confirm','cancel','reverse'):
            code='opening_balance.'+operation
            db.execute('DELETE FROM role_permissions WHERE permission_code=?',(code,))
            db.execute('DELETE FROM permissions WHERE code=?',(code,))
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='permission_groups'").fetchone():
            db.execute("DELETE FROM permission_groups WHERE code='finance.opening_balances'")
        for table in ('journal_attachment_reversals', 'journal_attachments',
                      'journal_changes', 'journal_lines', 'journals'):
            db.execute(f'DROP TABLE IF EXISTS {table}')
        for operation in ('view','create','submit','review','post','cancel','reverse','attachment'):
            code = 'journal.' + operation
            db.execute('DELETE FROM role_permissions WHERE permission_code = ?', (code,))
            db.execute('DELETE FROM permissions WHERE code = ?', (code,))
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='permission_groups'").fetchone():
            db.execute("DELETE FROM permission_groups WHERE code = 'finance.journals'")
    return remove


@pytest.fixture
def remove_v39_schema(remove_journal_schema):
    def remove(db):
        remove_journal_schema(db)
        for table in ('ledger_account_changes', 'accounting_period_changes',
                      'ledger_accounts', 'accounting_periods'):
            db.execute(f'DROP TABLE IF EXISTS {table}')
        for code in ('ledger_account.view', 'ledger_account.manage',
                     'accounting_period.view', 'accounting_period.manage'):
            db.execute('DELETE FROM role_permissions WHERE permission_code = ?', (code,))
            db.execute('DELETE FROM permissions WHERE code = ?', (code,))
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='permission_groups'").fetchone():
            db.execute("DELETE FROM permission_groups WHERE code IN ('finance.ledger_accounts','finance.accounting_periods')")
        for table in ('production_settlement_charges', 'production_settlement_dependencies',
                      'production_settlement_sources', 'production_cost_allocations',
                      'production_settlement_reversals', 'production_cost_settlements'):
            db.execute(f'DROP TABLE IF EXISTS {table}')
        for code in ('production_cost.settle', 'production_cost.reopen'):
            db.execute('DELETE FROM role_permissions WHERE permission_code = ?', (code,))
            db.execute('DELETE FROM permissions WHERE code = ?', (code,))
    return remove


@pytest.fixture(autouse=True)
def configure_numbering_for_business_fixtures(monkeypatch, request):
    """既有业务用例先完成新增初始化步骤；专门的编号测试自行验证未配置状态。"""
    if request.node.path.name == 'test_document_numbering.py':
        return
    from fastapi.testclient import TestClient
    original = TestClient.request

    def prepared(client, method, url, **kwargs):
        response = original(client, method, url, **kwargs)
        if str(url).endswith('/auth/login') and response.status_code == 200:
            login = response.json()
            if 'admin' in login['user']['roles']:
                headers = {'Authorization': 'Bearer ' + login['token']}
                current = original(client, 'GET', '/api/v1/system/document-numbering', headers=headers)
                if current.status_code == 200 and not current.json()['configured']:
                    configured = original(client, 'PUT', '/api/v1/system/document-numbering', headers=headers,
                        json={'style': 'english', 'timezone_mode': 'utc', 'timezone': None,
                              'version': current.json()['version']})
                    assert configured.status_code == 200, configured.text
        return response
    monkeypatch.setattr(TestClient, 'request', prepared)
