"""编号贯穿实际采购、生产、销售和资金流程，来源与导出保持一致。"""

from approval_test_helpers import approve_document

from test_business_orm import erp, receipt, completion
from test_business_journals import business, generate, source
from test_crm import seeded, base_records, approved, action, pdf_text, B, C
from test_equipment import erp as maintenance, approved as approved_job
from test_after_sales import erp as after_sales, payload as after_sales_payload


def test_numbered_purchase_production_sales_sources_and_exports(erp):
    client, request, supplier, customer, materials, _, purchase = erp
    assert purchase['document_no'].startswith('PO-')
    received = receipt(erp)
    assert received['purchase_order_document_no'] == purchase['document_no']
    assert received['document_no'].startswith('PIN-')
    request('POST', f'receipts/{received["id"]}/post')
    produced = completion(erp)
    request('POST', f'production-completions/{produced["id"]}/post')
    assert produced['document_no'].startswith('CMP-')
    assert produced['work_order_document_no'].startswith('WO-')
    sale = request('POST', 'sales-orders', dict(customer_id=customer, reference='客户合同',
        lines=[dict(material_id=materials[0], quantity='1', unit_price='8')]), 201)
    approve_document(client, dict(client.headers), 'SalesOrder', sale['id'])
    request('POST', f'sales-orders/{sale["id"]}/confirm')
    shipment = request('POST', 'shipments', dict(sales_order_id=sale['id'], warehouse_id=1,
        lines=[dict(material_id=materials[0], quantity='1')]), 201)
    assert shipment['sales_order_document_no'] == sale['document_no']
    approve_document(client, dict(client.headers), 'Shipment', shipment['id'])
    request('POST', f'shipments/{shipment["id"]}/post')
    paid = request('POST', 'finance/payment-records', dict(kind='receivable', order_id=sale['id'],
        action='settlement', amount='8', reference='外部银行流水'), 201)
    reverse = request('POST', f'finance/payment-records/{paid["id"]}/reverse', dict(reason='重新核对'), 201)
    assert paid['document_no'].startswith('PAY-') and reverse['document_no'] != paid['document_no']
    assert reverse['reverses_document_no'] == paid['document_no']
    assert request('GET', 'finance/overview')['payments'][0]['document_no'].startswith('PAY-')
    movements = request('POST', 'inventory-ledger/query', {})['rows']
    assert any(row['source_document_no'] == received['document_no'] for row in movements)
    assert any(row['source_document_no'] == produced['document_no'] for row in movements)
    report = request('POST', 'reports/query', dict(kind='receiving_returns'))
    assert received['document_no'] in report['csv']
    assert purchase['document_no'] in request('POST', 'reports/query', dict(kind='purchase_orders'))['csv']
    # 冲销来源指向原主单，库存冲销日志本身不冒充新的入库主单。
    approve_document(client, dict(client.headers), 'Shipment', shipment['id'], intent='reverse', reason='测试来源冲销')
    request('POST', f'shipments/{shipment["id"]}/reverse', dict(reason='测试来源冲销'), 201)
    movements = request('POST', 'inventory-ledger/query', {})['rows']
    assert next(row for row in movements if row['source_type'] == 'shipment_reversal')['source_document_no'] == shipment['document_no']


def test_generated_financial_journal_uses_own_number_and_preserves_fingerprint(business):
    client, request, _, _, original_erp = business
    received = receipt(original_erp)
    request('POST', f'receipts/{received["id"]}/post')
    key = f'receipt:{received["id"]}'
    before = source(client, key)
    assert before['source_document_no'] == received['document_no']
    journal = generate(client, key)
    assert journal['document_no'].startswith('JV-')
    after = source(client, key)
    assert after['journal_document_no'] == journal['document_no']
    assert before['fingerprint'] == after['fingerprint']


def test_maintenance_automatically_created_request_has_independent_number(maintenance):
    _, api, _, _, _, part = maintenance
    job = approved_job(maintenance, warehouse_id=1, parts=[dict(material_id=part, quantity='3')])
    assert job['document_no'].startswith('MNT-')
    job = api('POST', f'equipment/jobs/{job["id"]}/purchase-requests',
        dict(version=job['version'], reason='采购缺件', evidence='现场检修', parts=[dict(material_id=part, quantity='2')]), status=201)
    request = job['purchase_requests'][0]
    assert request['document_no'].startswith('PR-')
    assert request['document_no'] != job['document_no']


def test_quote_pdf_and_conversion_keep_independent_business_numbers(seeded):
    client, admin, _, seller, *_ = seeded
    _, opportunity, payload = base_records(seeded)
    quote = approved(seeded, payload)
    assert quote['document_no'].startswith('QUO-')
    # PDF 添加可读业务单号，但审批时冻结的外部参考号仍保留。
    response = client.get(C + f'/quotes/{quote["id"]}/pdf', headers=seller)
    assert response.status_code == 200
    _, text = pdf_text(response.content)
    assert quote['document_no'] in text and payload['reference'] in text
    converted = action(client, admin, quote, 'convert', acceptance_reference='客户确认',
                       opportunity_version=opportunity['version'])
    orders = client.get(B + '/sales-orders', headers=admin).json()
    order = next(row for row in orders if row['id'] == converted['sales_order_id'])
    assert order['document_no'].startswith('SO-')
    assert converted['sales_order_document_no'] == order['document_no']


def test_frozen_after_sales_evidence_keeps_ids_and_exposes_numbers_outside(after_sales):
    _, api, _, shipment, _, _, order = after_sales
    case = api('POST', 'after-sales/cases', after_sales_payload(after_sales), status=201)
    # 审核证据中的来源对象仍只含原字段，外层单号用于列表与详情溯源。
    assert case['shipment_document_no'] == shipment['document_no']
    assert case['sales_order_document_no'] == order['document_no']
    assert 'shipment_document_no' not in case['frozen_source']
    assert case['frozen_source']['shipment_id'] == shipment['id']
    assert api('GET', 'after-sales')['cases'][0]['shipment_document_no'] == shipment['document_no']
