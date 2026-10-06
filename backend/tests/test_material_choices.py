"""业务选料应获得辨认资料，同时保持原业务权限和历史单据契约。"""

import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.mark.parametrize('path,permission', [
    ('/crm/options', 'crm.view'), ('/after-sales', 'after_sales.view'),
    ('/equipment/overview', 'equipment.view'), ('/production-quality', 'quality.view'),
    ('/inventory/warnings', 'inventory.view'),
    ('/production/mrp/options', 'mrp.view'),
])
def test_choices_include_details_with_existing_business_permission(monkeypatch, tmp_path, path, permission):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'choices.db'))
    with TestClient(app, client=('127.0.0.1', 12000)) as client:
        prefix = '/api/v1'
        password = 'secure-pass-123'
        assert client.post(prefix + '/setup/admin', json={'username': 'admin', 'password': password}).status_code == 201

        def login(username):
            result = client.post(prefix + '/auth/login', json={'username': username, 'password': password})
            return {'Authorization': 'Bearer ' + result.json()['token']}

        admin = login('admin')
        material = dict(name='精密贴片电阻', unit='个', category_code='EL-SR', specification='10kΩ',
            package='0603', brand='示例品牌', manufacturer_part_number='RC0603-10K', electrical_value='10kΩ',
            tolerance='±1%', rated_voltage='50V', rated_power='0.1W', temperature_range='-55～155℃',
            compliance='RoHS', notes='采购时核对封装')
        created = client.post(prefix + '/materials', headers=admin, json=material)
        assert created.status_code == 201, created.text
        identifier = created.json()['id']
        # 自定义角色只具有原接口所需权限，不借用管理员或库存资料查看权限。
        for role, permissions in [('choice_reader', [permission]), ('choice_denied', [])]:
            assert client.post(prefix + '/roles', headers=admin,
                json={'code': role, 'label': role, 'permissions': permissions}).status_code == 201
            assert client.post(prefix + '/users', headers=admin,
                json={'username': role, 'password': password, 'roles': [role]}).status_code == 201
        reader = login('choice_reader')
        result = client.get(prefix + path, headers=reader)
        assert result.status_code == 200, result.text
        choice = next(row for row in result.json()['materials'] if row['id'] == identifier)
        assert {key: choice[key] for key in material} == material
        assert choice['category_name'] == '电子类 / 贴片电阻'
        assert choice['sku'].startswith('EL-SR-')
        assert 'supplier_ids' not in choice
        if permission != 'mrp.view':
            assert 'version' not in choice
        else:
            # 选项增加展示字段后，计算快照及其指纹必须仍来自原始来源。
            from app.core.orm import orm_session
            from app.production.mrp_sources import collect, fingerprint
            with orm_session() as db:
                snapshot = collect(db)
            assert result.json()['fingerprint'] == fingerprint(snapshot)
            assert all('category_name' not in row for row in snapshot['materials'])
        if permission != 'inventory.view':
            assert client.get(prefix + '/materials', headers=reader).status_code == 403
        assert client.get(prefix + path, headers=login('choice_denied')).status_code == 403
        assert client.get(prefix + path).status_code == 401
