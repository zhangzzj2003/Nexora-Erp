"""用户资料的保存、唯一工号、授权和旧账号升级回归。"""
import json
import sqlite3

from fastapi.testclient import TestClient
from app.main import app
from app.core.database import connection, migrate


def test_user_profile_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'profiles.db'))
    with TestClient(app, client=('127.0.0.1', 12345)) as client:
        base = '/api/v1'
        client.post(f'{base}/setup/admin', json={'username': 'admin', 'password': 'admin-password-123'})
        def login(name, password):
            token = client.post(f'{base}/auth/login', json={'username': name, 'password': password}).json()['token']
            return {'Authorization': f'Bearer {token}'}
        admin = login('admin', 'admin-password-123')
        profile = {'full_name': ' 张三 ', 'employee_no': ' E001 ', 'phone': ' 13800138000 ', 'roles': ['viewer']}
        payload = dict(profile, username='worker', password='worker-password-123')
        created = client.post(f'{base}/users', headers=admin, json=payload)
        assert created.status_code == 201, created.text
        worker = created.json()
        uid = worker['id']
        assert worker['full_name'] == '张三'
        assert worker['employee_no'] == 'E001'
        assert worker['phone'] == '13800138000'
        url = f'{base}/users/{uid}'
        other = login('worker', 'worker-password-123')
        assert client.put(url, headers=other, json=profile).status_code == 403
        assert client.put(f'{base}/users/999', headers=admin, json=profile).status_code == 404
        assert client.post(f'{base}/users', headers=admin, json=dict(payload, username='duplicate', employee_no='e001')).status_code == 409
        for bad in ({'phone': 'abc123'}, {'employee_no': 'bad space'}, {'full_name': '字' * 61}, {'roles': ['unknown']}):
            assert client.put(url, headers=admin, json=dict(profile, **bad)).status_code == 422
        updated = dict(profile, full_name='李四', employee_no='E002', phone='+86 13900139000', roles=['buyer'])
        saved = client.put(url, headers=admin, json=updated)
        assert saved.status_code == 200, saved.text
        assert saved.json()['roles'] == ['buyer']
        # 登录会话读取最新资料；修改审计不包含密码或会话令牌。
        assert client.get(f'{base}/auth/me', headers=other).json()['full_name'] == '李四'
        with connection() as db:
            change = db.execute('SELECT * FROM user_profile_changes').fetchone()
            assert change['changed_by'] == 1
            assert json.loads(change['before_json'])['employee_no'] == 'E001'
            assert json.loads(change['after_json'])['employee_no'] == 'E002'
            assert 'password' not in change['after_json']
        # 最后管理员角色保护和唯一工号冲突必须连资料一起回滚。
        admin_profile = dict(updated, employee_no='ADMIN', roles=['admin'])
        assert client.put(f'{base}/users/1', headers=admin, json=admin_profile).status_code == 200
        assert client.put(url, headers=admin, json=dict(updated, employee_no='admin', roles=['viewer'])).status_code == 409
        assert client.put(f'{base}/users/1', headers=admin, json=dict(updated, full_name='不能保存')).status_code == 409
        assert client.get(f'{base}/auth/me', headers=admin).json()['full_name'] == '李四'
        assert next(u for u in client.get(f'{base}/users', headers=admin).json() if u['id'] == uid)['roles'] == ['buyer']
        # 可清空旧资料；多位未填写工号的账号不冲突。
        assert client.put(url, headers=admin, json={'roles': ['viewer']}).status_code == 200
        assert client.post(f'{base}/users', headers=admin, json={'username': 'blank', 'password': 'blank-password-123', 'roles': ['viewer']}).status_code == 201
        assert client.put(f'{base}/users/{uid}/status', headers=admin, json={'is_active': False}).status_code == 200
        assert client.get(f'{base}/auth/me', headers=other).status_code == 401
        assert client.put(f'{base}/users/{uid}/status', headers=admin, json={'is_active': True}).status_code == 200
        assert client.post(f'{url}/reset-password', headers=admin, json={'password': 'new-password-123'}).status_code == 204
        assert client.post(f'{base}/auth/login', json={'username': 'worker', 'password': 'worker-password-123'}).status_code == 401
        assert client.post(f'{base}/auth/login', json={'username': 'worker', 'password': 'new-password-123'}).status_code == 200


def test_v36_users_gain_empty_profiles_without_losing_accounts(monkeypatch, tmp_path, remove_v39_schema):
    path = tmp_path / 'legacy.db'
    monkeypatch.setenv('NEXORA_DB_PATH', str(path))
    migrate()
    # 结算迁移依赖完整业务结构，旧用户表仍去掉本次验证的资料列。
    with sqlite3.connect(path) as db:
        db.execute('DROP INDEX users_employee_no')
        for column in ('full_name', 'employee_no', 'phone'):
            db.execute(f'ALTER TABLE users DROP COLUMN {column}')
        db.execute('DROP TABLE user_profile_changes')
        db.execute('DROP TABLE menu_icon_changes')
        db.execute('DROP TABLE menu_icons')
        db.execute("INSERT INTO users(id, username, password_hash, is_active) VALUES (7, 'legacy', 'retained-hash', 1)")
        remove_v39_schema(db)
        db.execute('PRAGMA user_version = 36')
    migrate()
    migrate()
    with connection() as db:
        row = db.execute('SELECT * FROM users').fetchone()
        assert row['id'] == 7 and row['password_hash'] == 'retained-hash'
        assert (row['full_name'], row['employee_no'], row['phone']) == ('', '', '')
        assert db.execute('PRAGMA user_version').fetchone()[0] == 69
