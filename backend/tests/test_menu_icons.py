"""图标配置的授权、持久化、并发冲突、恢复默认与迁移回归。"""
import sqlite3
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import connection, migrate


def test_menu_icons_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'menus.db'))
    with TestClient(app, client=('127.0.0.1', 12345)) as client:
        base = '/api/v1'
        client.post(f'{base}/setup/admin', json={'username': 'admin', 'password': 'admin-password-123'})
        def login(username, password):
            token = client.post(f'{base}/auth/login', json={'username': username, 'password': password}).json()['token']
            return {'Authorization': f'Bearer {token}'}
        admin = login('admin', 'admin-password-123')
        client.post(f'{base}/users', headers=admin, json={'username': 'viewer', 'password': 'viewer-password-123', 'roles': ['viewer']})
        viewer = login('viewer', 'viewer-password-123')
        url = f'{base}/menu-icons'
        payload = {'key': 'group:warehouse', 'icon': 'truck', 'version': 0}
        assert client.get(url).status_code == 401
        assert client.put(url, json=payload).status_code == 401
        assert client.get(url, headers=viewer).json() == []
        assert client.put(url, headers=viewer, json=payload).status_code == 403
        for bad in ({'key': 'route:unknown'}, {'icon': '<svg onload=alert(1)>'}, {'icon': 'https://remote/icon'}, {'version': -1}, {'version': True}, {'extra': 'field'}):
            assert client.put(url, headers=admin, json=dict(payload, **bad)).status_code == 422
        saved = client.put(url, headers=admin, json=payload)
        assert saved.status_code == 200, saved.text
        assert saved.json()['version'] == 1
        assert client.get(url, headers=viewer).json() == [dict(payload, version=1)]
        # 第二个管理员读到旧版本时必须冲突，不能覆盖第一个人的选择。
        assert client.put(url, headers=admin, json=dict(payload, icon='box')).status_code == 409
        assert client.put(url, headers=admin, json={'key':'route:home', 'icon':'chart', 'version':0}).status_code == 200
        assert client.put(url, headers=admin, json=dict(payload, icon=None, version=1)).json()['version'] == 2
        assert client.put(url, headers=admin, json=payload).status_code == 409
        with connection() as db:
            assert db.execute('SELECT COUNT(*) FROM menu_icon_changes').fetchone()[0] == 3
            assert db.execute("SELECT before_icon, after_icon FROM menu_icon_changes WHERE menu_key='group:warehouse' ORDER BY id DESC LIMIT 1").fetchone()[:] == ('truck', None)
    # 重启应用后依然保存配置与版本，不依赖浏览器本地缓存。
    with TestClient(app, client=('127.0.0.1', 12345)) as client:
        assert client.get('/api/v1/menu-icons', headers=viewer).json() == [
            {'key':'group:warehouse','icon':None,'version':2}, {'key':'route:home','icon':'chart','version':1}]


def test_upgrade_v37_keeps_existing_data(monkeypatch, tmp_path, remove_v39_schema):
    path = tmp_path / 'legacy.db'
    monkeypatch.setenv('NEXORA_DB_PATH', str(path))
    migrate()
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO users(id, username, password_hash) VALUES (7, 'retained', 'retained-hash')")
        db.execute('DROP TABLE menu_icon_changes')
        db.execute('DROP TABLE menu_icons')
        remove_v39_schema(db)
        db.execute('PRAGMA user_version = 37')
    migrate()
    migrate()
    with connection() as db:
        assert db.execute('SELECT username FROM users').fetchone()[0] == 'retained'
        assert db.execute('SELECT COUNT(*) FROM menu_icons').fetchone()[0] == 0
        assert db.execute('PRAGMA user_version').fetchone()[0] == 65
