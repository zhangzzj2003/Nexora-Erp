"""仓库自动编码、并发分配及物料种数回归，不连接正式数据库。"""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.core.models import StockMovement
from app.core.orm import orm_session
from app.main import app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'warehouse-catalog.db'))
    with TestClient(app, client=('127.0.0.1', 12000)) as client:
        account = {'username': 'admin', 'password': 'secure-pass-123'}
        assert client.post('/api/v1/setup/admin', json=account).status_code == 201
        token = client.post('/api/v1/auth/login', json=account).json()['token']
        client.headers['Authorization'] = f'Bearer {token}'
        yield client


def test_name_codes_preview_collision_and_legacy_compatibility(client):
    cases = [(' 原材料仓库 ', 'YCLCK'), ('重庆仓库', 'CQCK'), ('成品 A-01 仓', 'CPA01C'),
             ('West 02', 'WEST02'), ('😀', 'CK'), ('A' * 80, 'A' * 40)]
    for name, expected in cases:
        preview = client.post('/api/v1/warehouse-code-preview', json={'name': name})
        assert preview.status_code == 200
        assert preview.json() == {'code': expected}
        created = client.post('/api/v1/warehouses', json={'name': name})
        assert created.status_code == 201
        assert created.json()['code'] == expected
        assert created.json()['name'] == name.strip()
    # 重复名称仍报冲突，失败和预览都不产生多余的审计记录。
    assert client.post('/api/v1/warehouses', json={'name': '原材料仓库'}).status_code == 409
    assert len(client.get('/api/v1/warehouse-changes').json()) == len(cases)
    assert client.post('/api/v1/warehouses', json={'code': 'dc', 'name': '旧仓'}).json()['code'] == 'DC'
    assert client.post('/api/v1/warehouse-code-preview', json={'name': '东仓'}).json()['code'] == 'DC-2'
    # 两个客户端预览同一码后，真正保存仍在同一写事务内分配各自编码。
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda name: client.post('/api/v1/warehouses', json={'name': name}), ['东仓', '冬仓']))
    assert all(response.status_code == 201 for response in responses)
    assert {response.json()['code'] for response in responses} == {'DC-2', 'DC-3'}
    long_code = client.post('/api/v1/warehouses', json={'name': 'A' * 79 + 'B'}).json()['code']
    assert long_code == 'A' * 38 + '-2'
    created = responses[0].json()
    changed = client.put(f"/api/v1/warehouses/{created['id']}", json={
        'code': created['code'], 'name': '改名后的东仓', 'version': created['version'], 'reason': '调整名称'})
    assert changed.status_code == 200 and changed.json()['code'] == created['code']


def test_code_validation_and_permissions(client):
    for name in ['', '   ', '仓' * 81, 42]:
        assert client.post('/api/v1/warehouse-code-preview', json={'name': name}).status_code == 422
        assert client.post('/api/v1/warehouses', json={'name': name}).status_code == 422
    for code in ['', '中文', 'A' * 41, '../bad']:
        assert client.post('/api/v1/warehouses', json={'name': '东仓', 'code': code}).status_code == 422
    # 编辑仍必须提供原有编码、版本与原因，新增的可选编码不能放宽编辑校验。
    assert client.put('/api/v1/warehouses/1', json={'name': '新主仓', 'version': 1, 'reason': '更名'}).status_code == 422
    account = {'username': 'viewer', 'password': 'secure-pass-123', 'roles': ['viewer']}
    assert client.post('/api/v1/users', json=account).status_code == 201
    token = client.post('/api/v1/auth/login', json=account).json()['token']
    client.headers['Authorization'] = f'Bearer {token}'
    assert client.get('/api/v1/warehouses').status_code == 200
    assert client.post('/api/v1/warehouse-code-preview', json={'name': '东仓'}).status_code == 403
    assert client.post('/api/v1/warehouses', json={'name': '东仓'}).status_code == 403
    client.headers.clear()
    assert client.get('/api/v1/warehouses').status_code == 401


def test_material_counts_use_per_warehouse_positive_net_balance(client):
    east = client.post('/api/v1/warehouses', json={'name': '东仓'}).json()['id']
    empty = client.post('/api/v1/warehouses', json={'name': '空仓'}).json()['id']
    materials = [client.post('/api/v1/materials', json={
        'sku': f'COUNT-{index}', 'name': f'统计物料{index}', 'unit': '件'}).json()['id'] for index in range(5)]
    # 用底层流水构造精确抵消、负数、微量和多笔同物料，避免用浮点求和掩盖统计错误。
    samples = [(1, 0, '0.1'), (1, 0, '0.2'), (1, 0, '-0.3'),
               (1, 1, '4'), (1, 1, '3'), (1, 1, '-2'), (1, 2, '-1'), (1, 3, '0.001'),
               (east, 0, '2'), (east, 1, '1'), (east, 1, '-1')]
    with orm_session(write=True) as db:
        db.add_all([StockMovement(warehouse_id=warehouse, material_id=materials[index], quantity=quantity,
                    source_type='other_inbound', source_id=1, source_line_id=line + 1, created_by=1)
                    for line, (warehouse, index, quantity) in enumerate(samples)])
    rows = client.get('/api/v1/warehouses').json()
    assert {row['id']: row['material_count'] for row in rows} == {1: 2, east: 1, empty: 0}
    # 动态统计不混入档案变更快照；刷新时物料归零会从种数中移除。
    assert 'material_count' not in client.get(f'/api/v1/warehouses/{east}').json()
    with orm_session(write=True) as db:
        db.add(StockMovement(warehouse_id=east, material_id=materials[0], quantity='-2',
                            source_type='other_outbound', source_id=2, source_line_id=99, created_by=1))
    assert next(row for row in client.get('/api/v1/warehouses').json() if row['id'] == east)['material_count'] == 0
