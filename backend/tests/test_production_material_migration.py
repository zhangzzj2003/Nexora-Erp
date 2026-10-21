"""第 103 版保留旧直接领料证据，旧未执行审批必须重新核对签收语义。"""

from approval_test_helpers import planned_order

import hashlib
import json
import sqlite3

from approval_test_helpers import approve_document
from app.core.database import database_path, migrate
from app.core.orm import orm_session
from app.production.work_orders import issued_quantity
from test_production_settlements import erp


def restore_v102_material_schema(path):
    # 仅旧库测试夹具回退新增结构；模拟真实 v102 已出库事实及当时的审批正文。
    with sqlite3.connect(path) as db:
        for identifier, snapshot in db.execute("SELECT id,snapshot_json FROM document_approval_cases WHERE document_type='MaterialIssue'").fetchall():
            value = json.loads(snapshot)
            value.pop('receipt_required', None)
            encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            db.execute('UPDATE document_approval_cases SET snapshot_json=?,content_digest=? WHERE id=?',
                (encoded, hashlib.sha256(encoded.encode()).hexdigest(), identifier))
        for table in ('production_flow_settlement_sources', 'material_flow_execution_lots', 'material_flow_execution_lines', 'material_flow_executions',
                      'material_flow_lines', 'material_receipts', 'material_dispatches', 'material_exchanges', 'production_material_returns'):
            db.execute(f'DROP TABLE {table}')
        db.execute('ALTER TABLE material_issues DROP COLUMN historical_direct')
        db.execute('PRAGMA user_version=102')


def test_upgrade_preserves_historical_issue_and_requires_new_approval_for_old_draft(erp):
    client, headers, api, material, receipt, work_order, *_ = erp
    raw, product = material('UPGRADE-RAW'), material('UPGRADE-PRODUCT')
    receipt(raw, '20', '2')
    posted_order, posted_issue = work_order(raw, product, '2')
    draft_order = planned_order(api, {'bom_id': posted_order['bom_id'], 'warehouse_id': 1, 'target_quantity': '2'}, 201)
    approve_document(client, headers, 'WorkOrder', draft_order['id'])
    api('POST', f'work-orders/{draft_order["id"]}/release')
    pending_issue = api('POST', 'material-issues', {'work_order_id': draft_order['id'], 'warehouse_id': 1,
        'lines': [{'work_order_line_id': draft_order['lines'][0]['id'], 'quantity': '2'}]}, 201)
    approve_document(client, headers, 'MaterialIssue', pending_issue['id'])
    movements_before = api('GET', 'movements')
    restore_v102_material_schema(database_path())
    migrate()
    migrate()
    with sqlite3.connect(database_path()) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 111
        assert db.execute('SELECT historical_direct FROM material_issues WHERE id=?', (posted_issue['id'],)).fetchone()[0] == 1
        assert db.execute('SELECT historical_direct FROM material_issues WHERE id=?', (pending_issue['id'],)).fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM material_receipts').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM material_flow_execution_lines').fetchone()[0] == 0
    assert api('GET', 'movements') == movements_before
    # 权限目录区分自动签收单与人工建单，不产生无法使用的签收建单/关闭按钮权限。
    permission_codes={row['code'] for row in api('GET','permissions')}
    assert {'material_receipt.sign','material_receipt.handover_return','material_receipt.reverse'}<=permission_codes
    assert not {'material_receipt.create','material_receipt.post','material_receipt.close'} & permission_codes
    historical = next(row for row in api('GET', 'material-issues') if row['id'] == posted_issue['id'])
    assert historical['document_no'] == posted_issue['document_no']
    assert historical['receipt_mode'] == 'historical_direct' and historical['material_receipt_id'] is None
    with orm_session() as db:
        assert issued_quantity(db, posted_order['lines'][0]['id']) == 2
    # 原审批批准的是旧直接领料正文，升级后不能凭原批准跳过新增签收边界。
    api('POST', f'material-issues/{pending_issue["id"]}/post', status=409)
    path = f'system/document-approvals/MaterialIssue/{pending_issue["id"]}'
    approval = api('GET', path)
    api('POST', path + '/withdraw', {'version': approval['version'], 'intent': 'execute', 'reason': '按升级后的发料签收规则重新核对'})
    approve_document(client, headers, 'MaterialIssue', pending_issue['id'])
    posted = api('POST', f'material-issues/{pending_issue["id"]}/post')
    assert posted['material_receipt_id'] is not None
    with orm_session() as db:
        assert issued_quantity(db, draft_order['lines'][0]['id']) == 0
