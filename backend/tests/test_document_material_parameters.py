"""单据参数以真实物料身份只读附加，不改变原权限、审批依据及批量查询边界。"""

import copy
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from app.main import app
from app.core.database import database_path
from app.core.orm import engine_for, orm_session
from app.core.models import DocumentApprovalCase, Material, MaterialSpecField, WorkOrder, ProductionCompletion
from app.core.approval_documents import document_summary, inbound_snapshot
from app.inventory.inbounds import inbound_data
from app.production.boms import bom_data
from approval_test_helpers import approve_document


@pytest.fixture
def details(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'material-parameters.db'))
    with TestClient(app, client=('127.0.0.1', 12000)) as client:
        base = '/api/v1/'
        password = 'secure-pass-123'
        assert client.post(base + 'setup/admin', json={'username': 'admin', 'password': password}).status_code == 201

        def login(name):
            response = client.post(base + 'auth/login', json={'username': name, 'password': password})
            assert response.status_code == 200, response.text
            return {'Authorization': 'Bearer ' + response.json()['token']}

        auth = login('admin')

        def api(method, path, body=None, status=200, headers=None):
            response = client.request(method, base + path, json=body, headers=auth if headers is None else headers)
            assert response.status_code == status, response.text
            return response.json() if status != 204 else None

        def role(name, permissions):
            api('POST', 'roles', {'code': name, 'label': name, 'permissions': permissions}, 201)
            api('POST', 'users', {'username': name, 'password': password, 'roles': [name]}, 201)
            return login(name)

        raw = api('POST', 'materials', {'name': '精密控制元件', 'unit': '个', 'category_code': 'EL-SR',
            'specification': '10kΩ', 'package': '0603', 'brand': '参数测试品牌',
            'manufacturer_part_number': 'PARAM-0603', 'electrical_value': '10kΩ',
            'tolerance': '±1%', 'rated_voltage': '50V', 'rated_power': '0.1W',
            'temperature_range': '-55～155℃', 'compliance': 'RoHS', 'notes': '当前档案参数'}, 201)
        product = api('POST', 'materials', {'name': '参数测试成品', 'unit': '台', 'category_code': 'EL-PC'}, 201)
        # 通过 ORM 建立各参数状态及停用历史字段，读取路径仍完全走真实 HTTP/serializer。
        with orm_session(write=True) as db:
            values = []
            for name, kind, status, value, enabled in [
                ('数值零', 'number', 'filled', '0', True), ('布尔否', 'boolean', 'filled', False, True),
                ('未知项', 'text', 'unknown', None, True), ('不适用项', 'text', 'not_applicable', None, True),
                ('待确认项', 'text', 'pending', None, True), ('旧规格', 'text', 'filled', '保留旧值', False)
            ]:
                field = MaterialSpecField(category_code='EL-SR', name=name, kind=kind, enabled=enabled, unit='')
                db.add(field); db.flush()
                values.append({'field_id': field.id, 'category_code': 'EL-SR', 'name': name,
                    'kind': kind, 'unit': '', 'status': status, 'value': value, 'source': '测试工程图纸'})
            material = db.get(Material, raw['id'])
            material.spec_values_json = json.dumps(values, ensure_ascii=False)
            material.spec_template_version = 1
            material.extra_attributes_json = json.dumps([{'name': '特殊处理', 'value': '防潮', 'unit': ''}], ensure_ascii=False)
        bom = api('POST', 'boms', {'product_material_id': product['id'], 'lines': [
            {'component_material_id': raw['id'], 'quantity': '2'}]}, 201)
        inbound = api('POST', 'warehouse-inbounds', {'warehouse_id': 1, 'reason': 'other',
            'note': '核对物料参数', 'lines': [{'material_id': raw['id'], 'quantity': '100'}]}, 201)
        yield client, auth, api, role, raw, product, bom, inbound


def assert_material(choice, identifier):
    assert choice['id'] == identifier
    assert choice['package'] == '0603' and choice['brand'] == '参数测试品牌'
    assert choice['category_name'] == '电子类 / 贴片电阻'
    assert choice['manufacturer_part_number'] == 'PARAM-0603'
    assert choice['extra_attributes'] == [{'name': '特殊处理', 'value': '防潮', 'unit': ''}]
    values = {item['name']: item for item in choice['spec_values']}
    assert values['数值零']['value'] == '0' and values['布尔否']['value'] is False
    assert [values[name]['status'] for name in ['未知项', '不适用项', '待确认项']] == ['unknown', 'not_applicable', 'pending']
    assert values['旧规格']['historical'] is True
    assert values['数值零']['historical'] is False
    # 辨认资料不能夹带编辑绑定、成本或售价；历史单据自身已有的价格不在此处重写。
    assert not {'supplier_ids', 'suppliers', 'version', 'unit_price', 'unit_cost', 'amount', 'line_total'} & choice.keys()


def test_bom_and_inbound_details_keep_business_permissions_and_real_line_identity(details):
    client, _, api, role, raw, _, bom, inbound = details
    for name, permissions, path, line_key, identifier in [
        ('bom_parameters', ['production.view'], f'boms/{bom["id"]}', 'component_material_id', bom['id']),
        ('inbound_parameters', ['other_inbound.view'], 'warehouse-inbounds', 'material_id', inbound['id'])
    ]:
        reader = role(name, permissions)
        result = api('GET', path, headers=reader)
        record = next(row for row in result if row['id'] == identifier) if isinstance(result, list) else result
        line = record['lines'][0]
        assert line[line_key] == raw['id']
        assert_material(line['material'], raw['id'])
        assert client.get('/api/v1/materials', headers=reader).status_code == 403
        assert client.get('/api/v1/' + path).status_code == 401
    denied = role('parameter_denied', [])
    assert client.get(f'/api/v1/boms/{bom["id"]}', headers=denied).status_code == 403
    assert client.get('/api/v1/warehouse-inbounds', headers=denied).status_code == 403


def test_current_parameters_never_change_approved_snapshot_digest_or_quantity(details):
    client, auth, api, role, raw, _, _, inbound = details
    approve_document(client, auth, 'WarehouseInbound', inbound['id'])
    endpoint = f'system/document-approvals/WarehouseInbound/{inbound["id"]}'
    reader = role('inbound_summary', ['other_inbound.view'])
    before = api('GET', endpoint, headers=reader)
    denied = role('summary_denied', [])
    assert client.get('/api/v1/' + endpoint, headers=denied).status_code == 403
    assert client.get('/api/v1/' + endpoint).status_code == 401
    entry = next(item for item in before['summary'] if item.get('material_id') == raw['id'])
    assert_material(entry['material'], raw['id'])
    assert entry['value'] == '100 个' and before['content_matches']
    with orm_session() as db:
        case = db.scalar(select(DocumentApprovalCase).where(DocumentApprovalCase.document_type == 'WarehouseInbound',
            DocumentApprovalCase.document_id == inbound['id']))
        frozen = (case.snapshot_json, case.content_digest, case.version)
        assert 'material' not in json.loads(case.snapshot_json)['lines'][0]
    with orm_session(write=True) as db:
        material = db.get(Material, raw['id'])
        material.package = '0805'; material.brand = '更新后的品牌'; material.notes = '更新当前参考参数'
    after = api('GET', endpoint, headers=reader)
    latest = next(item for item in after['summary'] if item.get('material_id') == raw['id'])
    assert latest['material']['package'] == '0805' and latest['material']['brand'] == '更新后的品牌'
    assert latest['value'] == entry['value']
    assert after['content_matches'] is True
    assert (after['status'], after['version'], after['events']) == (before['status'], before['version'], before['events'])
    with orm_session() as db:
        case = db.scalar(select(DocumentApprovalCase).where(DocumentApprovalCase.document_type == 'WarehouseInbound',
            DocumentApprovalCase.document_id == inbound['id']))
        assert (case.snapshot_json, case.content_digest, case.version) == frozen


def test_production_flow_association_and_product_target_reuse_existing_view_permissions(details):
    client, auth, api, role, raw, product, bom, _ = details
    api('POST', f'boms/{bom["id"]}/activate')
    work = api('POST', 'work-orders', {'bom_id': bom['id'], 'warehouse_id': 1, 'target_quantity': '2'}, 201)
    work_summary = api('GET', f'system/document-approvals/WorkOrder/{work["id"]}')['summary']
    assert next(item for item in work_summary if item['label'] == '成品目标')['material']['id'] == product['id']
    assert_material(next(item for item in work_summary if item.get('material_id') == raw['id'])['material'], raw['id'])
    approve_document(client, auth, 'WorkOrder', work['id'])
    api('POST', f'work-orders/{work["id"]}/release')
    dispatch = api('POST', 'material-dispatches', {'request_id': str(uuid4()), 'work_order_id': work['id'],
        'warehouse_id': 1, 'reason': '测试参数', 'lines': [{'work_order_line_id': work['lines'][0]['id'], 'quantity': '2'}]}, 201)
    flow_reader = role('flow_parameters', ['material_flow.view'])
    read = api('GET', f'material-dispatches/{dispatch["id"]}', headers=flow_reader)
    assert_material(read['lines'][0]['material'], raw['id'])
    summary_lines = api('GET', f'work-orders/{work["id"]}/material-flow', headers=flow_reader)['lines']
    assert_material(summary_lines[0]['material'], raw['id'])
    summary = api('GET', f'system/document-approvals/MaterialDispatch/{dispatch["id"]}', headers=flow_reader)['summary']
    assert_material(next(item for item in summary if item.get('material_id') == raw['id'])['material'], raw['id'])
    production_reader = role('association_parameters', ['production.view'])
    association = api('GET', f'work-orders/{work["id"]}/associations?include_references=true', headers=production_reader)
    assert_material(association['components'][0]['material'], raw['id'])
    assert association['inventory_visible'] is False and association['components'][0]['purchase_references'] == []
    assert client.get('/api/v1/materials', headers=flow_reader).status_code == 403
    assert client.get('/api/v1/materials', headers=production_reader).status_code == 403


@pytest.mark.parametrize('kind', ['CrmQuote', 'MaintenanceJob', 'MrpPlan', 'AfterSalesCase'])
def test_early_summary_branches_attach_only_known_materials_and_preserve_fixed_text(details, kind):
    _, _, _, _, raw, _, _, _ = details
    line = {'material_id': raw['id'], 'sku': '固定旧编码', 'material_name': '固定旧名称', 'quantity': '0.125', 'unit': '个', 'unit_price': '3'}
    if kind == 'CrmQuote':
        content = {'party_json': json.dumps({'customer_name': '客户', 'contact_name': '联系人', 'phone': '', 'email': ''}),
            'reference': '报价', 'valid_until': '2026-12-01', 'terms': '原商务条款', 'attachments': [],
            'lines': [line, {**line, 'material_id': None, 'material_name': '自由文本服务'}]}
    elif kind == 'MaintenanceJob':
        content = {'equipment_json': json.dumps({'code': 'E01', 'name': '设备', 'location': '车间'}), 'assigned_to': 1,
            'reference': '维护', 'kind': 'preventive', 'plan_due_date': '2026-12-01', 'plan_due_hours': None,
            'request_note': '固定维护方案', 'work_order_id': None, 'parts_json': json.dumps([line]), 'attachments': []}
    elif kind == 'MrpPlan':
        content = {'reference': '计划', 'input_json': json.dumps({'start_date': '2026-12-01', 'reason': '原编制依据'}),
            'fingerprint': '固定指纹', 'snapshot_json': json.dumps({'suggestions': [{**line, 'name': '固定旧名称',
                'due_date': '2026-12-01', 'supply_mode': 'buy'}], 'warnings': []})}
    else:
        content = {'source_json': json.dumps({'customer_name': '客户', 'sku': '固定旧编码', 'material_name': '固定旧名称',
            'material_id': raw['id'], 'unit': '个', 'replacement': line}), 'shipment_line_id': 1,
            'reference': '售后', 'kind': 'repair', 'quantity': '1', 'complaint': '原诉求', 'solution': '原方案',
            'customer_acceptance': '同意', 'charge_mode': 'free', 'fee_amount': '0', 'warranty_basis': '',
            'parts_json': json.dumps([line]), 'attachments': []}
    before = copy.deepcopy(content)
    with orm_session() as db:
        summary = document_summary(db, kind, content)
    entries = [entry for entry in summary if entry.get('material_id') == raw['id']]
    assert entries
    for entry in entries:
        assert_material(entry['material'], raw['id'])
    assert content == before, '只读展示不允许把当前资料写入固定正文或 JSON'
    if kind == 'CrmQuote':
        assert entries[0]['label'] == '固定旧编码 · 固定旧名称'
        assert entries[0]['value'] == '0.125 个；单价 ¥3'
        assert 'material' not in next(item for item in summary if '自由文本服务' in item['label'])


def test_quality_summary_product_and_extra_material_keep_distinct_real_identities(details):
    _, _, _, _, raw, product, bom, _ = details
    with orm_session(write=True) as db:
        work = WorkOrder(bom_id=bom['id'], warehouse_id=1, target_quantity='1', created_by=1)
        db.add(work); db.flush()
        completion = ProductionCompletion(work_order_id=work.id, reported_quantity='1', created_by=1)
        db.add(completion); db.flush(); completion_id = completion.id
    content = {'source_json': json.dumps({'product_material_id': product['id'], 'product_sku': '固定成品编码',
        'product_name': '固定成品名称', 'product_unit': '台', 'qc_note': '固定质检记录'}),
        'completion_id': completion_id, 'reference': '返工依据', 'kind': 'rework', 'quantity': '1',
        'loss_treatment': 'carry', 'defect': '固定缺陷', 'action_note': '修复', 'warehouse_id': 1,
        'materials_json': json.dumps([{'material_id': raw['id'], 'sku': '固定辅料编码',
            'material_name': '固定辅料名称', 'quantity': '0.125', 'unit': '个'}])}
    before = copy.deepcopy(content)
    with orm_session() as db:
        summary = document_summary(db, 'QualityDisposition', content)
    target = next(item for item in summary if item['label'] == '成品')
    assert target['material_id'] == product['id'] and target['material']['id'] == product['id']
    assert target['value'] == '固定成品编码 · 固定成品名称'
    extra = next(item for item in summary if item['label'] == '追加材料')
    assert_material(extra['material'], raw['id'])
    assert extra['value'] == '固定辅料编码 · 固定辅料名称 × 0.125 个'
    assert content == before


@pytest.mark.parametrize('kind', ['bom', 'inbound', 'summary'])
def test_one_and_one_hundred_lines_keep_bounded_selects_and_response_payload(details, kind):
    _, _, api, _, raw, product, _, _ = details
    with orm_session(write=True) as db:
        original = db.get(Material, raw['id'])
        # 复制真实辨认资料生成百个不同身份，不能以重复同一 ID 掩盖逐行读取。
        rows = [Material(sku=f'PARAM-PERF-{index}', name=f'性能物料{index}', unit='个', category_code='EL-SR',
            package=original.package, brand=original.brand, spec_values_json=original.spec_values_json,
            extra_attributes_json=original.extra_attributes_json, spec_template_version=1) for index in range(100)]
        db.add_all(rows); db.flush(); identifiers = [row.id for row in rows]
    engine = engine_for(database_path().resolve())
    measurements = []
    for count in (1, 100):
        selected = identifiers[:count]
        if kind == 'bom':
            record = api('POST', 'boms', {'product_material_id': product['id'], 'lines': [
                {'component_material_id': identifier, 'quantity': '1'} for identifier in selected]}, 201)
        else:
            record = api('POST', 'warehouse-inbounds', {'warehouse_id': 1, 'reason': 'other', 'note': '批量资料',
                'lines': [{'material_id': identifier, 'quantity': '1'} for identifier in selected]}, 201)
        statements = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith('SELECT'):
                statements.append(statement)

        event.listen(engine, 'before_cursor_execute', capture)
        try:
            with orm_session() as db:
                result = bom_data(db, record['id']) if kind == 'bom' else inbound_data(db, record['id']) if kind == 'inbound' else (
                    document_summary(db, 'WarehouseInbound', inbound_snapshot(db, record['id'])))
        finally:
            event.remove(engine, 'before_cursor_execute', capture)
        details_rows = result if isinstance(result, list) else result['lines']
        assert len([row for row in details_rows if 'material' in row]) == count
        measurements.append((len(statements), len(json.dumps(result, ensure_ascii=False).encode())))
    assert measurements[1][0] <= measurements[0][0] + 1, measurements
    # 标准满字段百行响应设置明确预算，防止误把整库、供应商或业务历史重复塞入每行。
    assert measurements[1][1] < 300_000, measurements
    print(f'{kind} SELECT/body bytes 1vs100: {measurements}')
