"""销售退货批次必须来自原出库或明确登记为退回新批次。"""

from approval_test_helpers import approve_document

from fastapi.testclient import TestClient

from app.main import app


def test_sales_return_lots_source_and_reversal(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'return-lots.db'))
    with TestClient(app, client=('127.0.0.1', 12000)) as client:
        base = '/api/v1'
        client.post(f'{base}/setup/admin', json={'username': 'admin', 'password': 'secure-pass-123'})
        token = client.post(f'{base}/auth/login', json={
            'username': 'admin', 'password': 'secure-pass-123'}).json()['token']
        headers = {'Authorization': f'Bearer {token}'}
        supplier = client.post(f'{base}/suppliers', headers=headers, json={'name': '供应商'}).json()['id']
        customer = client.post(f'{base}/customers', headers=headers, json={'name': '客户'}).json()['id']
        material = client.post(f'{base}/materials', headers=headers, json={
            'sku': 'SR-LOT', 'name': '退货物料', 'unit': '件'}).json()['id']
        warehouse = client.post(f'{base}/warehouses', headers=headers, json={
            'code': 'RET', 'name': '退货仓'}).json()['id']
        receipt = client.post(f'{base}/receipts', headers=headers, json={
            'supplier_id': supplier, 'lines': [{'material_id': material, 'quantity': '2.000'}]}).json()
        # 业务前置单据通过真实独立审批，再验证原领域的库存、数量或金额约束。
        approve_document(client, headers, 'Receipt', receipt['id'])
        posted = client.post(f'{base}/receipts/{receipt["id"]}/post', headers=headers, json={
            'lines': [{'receipt_line_id': receipt['lines'][0]['id'], 'lots': [
                {'quantity': '1.000', 'supplier_lot': 'ORIGINAL-A'},
                {'quantity': '1.000', 'supplier_lot': 'ORIGINAL-B'}]}]})
        assert posted.status_code == 200
        source_lot = posted.json()['lines'][0]['physical_lots'][0]['id']
        other_lot = posted.json()['lines'][0]['physical_lots'][1]['id']
        order = client.post(f'{base}/sales-orders', headers=headers, json={
            'customer_id': customer, 'lines': [{'material_id': material,
                                                 'quantity': '2.000', 'unit_price': '10.0000'}]}).json()
        assert client.post(f'{base}/sales-orders/{order["id"]}/confirm', headers=headers).status_code == 200
        shipment = client.post(f'{base}/shipments', headers=headers, json={
            'sales_order_id': order['id'], 'warehouse_id': 1,
            'lines': [{'material_id': material, 'quantity': '2.000'}]}).json()
        source_line = shipment['lines'][0]['id']
        assert client.post(f'{base}/shipments/{shipment["id"]}/post', headers=headers, json={
            'lines': [{'shipment_line_id': source_line, 'lots': [
                {'lot_id': source_lot, 'quantity': '1.000'},
                {'lot_id': other_lot, 'quantity': '1.000'}]}]}).status_code == 200
        returned = client.post(f'{base}/sales-returns', headers=headers, json={
            'shipment_id': shipment['id'], 'warehouse_id': warehouse, 'reason': '客户退回',
            'lines': [{'shipment_line_id': source_line, 'quantity': '1.500'}]}).json()
        return_id, return_line = returned['id'], returned['lines'][0]['id']
        url = f'{base}/sales-returns/{return_id}'
        options = client.get(f'{url}/available-lots', headers=headers)
        assert options.status_code == 200
        assert options.json()['lines'][0]['lots'][0]['quantity'] == '1.000'
        assert options.json()['lines'][0]['lots'][0]['lot_id'] == source_lot
        wrong = client.post(f'{url}/post', headers=headers, json={'lines': [
            {'return_line_id': return_line, 'lots': [{'lot_id': 9999, 'quantity': '1.500'}]}]})
        assert wrong.status_code == 422
        excessive = client.post(f'{url}/post', headers=headers, json={'lines': [
            {'return_line_id': return_line, 'lots': [{'lot_id': source_lot, 'quantity': '1.501'}]}]})
        assert excessive.status_code == 422
        body = {'lines': [{'return_line_id': return_line, 'lots': [
            {'lot_id': source_lot, 'quantity': '1.000'},
            {'quantity': '0.500', 'supplier_lot': 'RETURNED'}]}]}
        posted_return = client.post(f'{url}/post', headers=headers, json=body)
        assert posted_return.status_code == 200, posted_return.text
        parts = posted_return.json()['lines'][0]['physical_lots']
        assert [part['quantity'] for part in parts] == ['1.000', '0.500']
        assert parts[1]['source_kind'] == 'sales_return'
        new_lot = parts[1]['id']
        history = client.get(f'{base}/inventory/physical-lots/{new_lot}/history', headers=headers).json()
        assert history['lot']['origin_movement_id'] == history['movements'][0]['movement_id']
        assert history['movements'][0]['source_type'] == 'sales_return'
        assert client.get(f'{url}/available-lots', headers=headers).status_code == 409
        later = client.post(f'{base}/sales-returns', headers=headers, json={
            'shipment_id': shipment['id'], 'warehouse_id': warehouse, 'reason': '剩余退回',
            'lines': [{'shipment_line_id': source_line, 'quantity': '0.500'}]}).json()
        later_options = client.get(f'{base}/sales-returns/{later["id"]}/available-lots',
                                   headers=headers).json()['lines'][0]['lots']
        assert len(later_options) == 1
        assert later_options[0]['lot_id'] == other_lot
        assert later_options[0]['quantity'] == '1.000'
        assert client.post(f'{base}/sales-returns/{later["id"]}/post', headers=headers,
                           json={'lines': [{'return_line_id': later['lines'][0]['id'], 'lots': [
                               {'lot_id': source_lot, 'quantity': '0.500'}]}]}).status_code == 409
        assert client.post(f'{base}/sales-returns/{later["id"]}/post', headers=headers,
                           json={'lines': [{'return_line_id': later['lines'][0]['id'], 'lots': [
                               {'lot_id': other_lot, 'quantity': '0.500'}]}]}).status_code == 200
        # 消耗退回批次后，原退货不得生成半套冲销流水。
        outbound = client.post(f'{base}/warehouse-outbounds', headers=headers, json={
            'warehouse_id': warehouse, 'reason': 'sample', 'note': '借出',
            'lines': [{'material_id': material, 'quantity': '0.500'}]}).json()
        outbound_id = outbound['id']
        assert client.post(f'{base}/warehouse-outbounds/{outbound_id}/post', headers=headers, json={
            'lines': [{'outbound_line_id': outbound['lines'][0]['id'], 'lots': [
                {'lot_id': new_lot, 'quantity': '0.500'}]}]}).status_code == 200
        reverse = f'{url}/reverse'
        assert client.post(reverse, headers=headers, json={'reason': '误退'}).status_code == 409
        assert client.post(f'{base}/warehouse-outbounds/{outbound_id}/reverse', headers=headers,
                           json={'reason': '归还'}).status_code == 201
        reversal = client.post(reverse, headers=headers, json={'reason': '误退'})
        assert reversal.status_code == 201, reversal.text
        reversed_history = client.get(f'{base}/inventory/physical-lots/{new_lot}/history',
                                      headers=headers).json()['movements']
        assert reversed_history[-1]['source_type'] == 'sales_return_reversal'
        assert reversed_history[-1]['original_allocation_id'] == history['movements'][0]['id']
