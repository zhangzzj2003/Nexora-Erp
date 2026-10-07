"""验证演示物料导入的幂等性、审计、权限与整批回滚。"""

import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.models import Material, MaterialCategory, MaterialSpecField, MaterialChange, MaterialCodeSequence, ServerIdentity, User
from app.core.orm import orm_session
from app.main import app

# 工具不加入服务启动链；测试直接加载它，避免为了导入工具改变业务路由。
script = Path(__file__).resolve().parents[2] / 'scripts/demo/import_materials.py'
spec = importlib.util.spec_from_file_location('demo_material_import', script)
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


def instance_id():
    with orm_session() as db:
        return db.scalar(select(ServerIdentity.id))


@pytest.fixture
def target(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'demo.db'))
    with TestClient(app, client=('127.0.0.1', 12000)) as client:
        assert client.post('/api/v1/setup/admin', json={
            'username': 'admin', 'password': 'secure-pass-123'}).status_code == 201
        yield demo.load_materials(script.with_name('materials.json'))


def test_import_and_repeat_preserve_existing_and_edited_materials(target):
    with orm_session(write=True) as db:
        db.add(Material(sku='OLD-001', name='原有物料', unit='件'))
    assert demo.import_materials(target, 1, instance_id()) == {'created': 50, 'skipped': 0}
    with orm_session(write=True) as db:
        row = db.scalar(select(Material).where(Material.manufacturer_part_number == 'DEMO-R10K-0603'))
        row.specification = '用户已编辑规格'
        row.version += 1
    assert demo.import_materials(target, 1, instance_id()) == {'created': 0, 'skipped': 50}
    with orm_session() as db:
        materials = list(db.scalars(select(Material)))
        audits = list(db.scalars(select(MaterialChange)))
        assert len(materials) == 51 and len({m.sku for m in materials}) == 51
        assert len(audits) == 50 and {a.changed_by for a in audits} == {1}
        assert all(a.action == 'create' and a.reason for a in audits)
        assert next(m for m in materials if m.sku == 'OLD-001').name == '原有物料'
        assert next(m for m in materials if m.manufacturer_part_number == 'DEMO-R10K-0603').specification == '用户已编辑规格'
        assert sum(s.last_number for s in db.scalars(select(MaterialCodeSequence))) == 50


@pytest.mark.parametrize('bad', [dict(category_code='INVALID'), dict(sku='MANUAL'),
    dict(name='正式物料'), dict(notes=''), dict(quantity=1), dict(version=1)])
def test_invalid_input_rejected_before_import(tmp_path, bad):
    raw = json.loads(script.with_name('materials.json').read_text(encoding='utf-8'))
    raw[-1].update(bad)
    path = tmp_path / 'bad.json'
    path.write_text(json.dumps(raw), encoding='utf-8')
    with pytest.raises(ValueError):
        demo.load_materials(path)


def test_duplicate_input_rejected(tmp_path):
    raw = json.loads(script.with_name('materials.json').read_text(encoding='utf-8'))
    raw.append(raw[0])
    path = tmp_path / 'duplicate.json'
    path.write_text(json.dumps(raw), encoding='utf-8')
    with pytest.raises(ValueError, match='料号重复'):
        demo.load_materials(path)


@pytest.mark.parametrize('constraint', ['disabled', 'required'])
def test_import_respects_dynamic_category_and_spec_rules(target, constraint):
    # 在整批末项施加新约束，验证前面已分配的编码和档案也一起回滚。
    code = target[-1].category_code
    with orm_session(write=True) as db:
        if constraint == 'disabled':
            db.get(MaterialCategory, code).enabled = False
        else:
            db.add(MaterialSpecField(category_code=code, name='客户必填参数', kind='text', required=True))
    with pytest.raises(ValueError):
        demo.import_materials(target, 1, instance_id())
    with orm_session() as db:
        assert list(db.scalars(select(Material))) == []
        assert list(db.scalars(select(MaterialChange))) == []
        assert list(db.scalars(select(MaterialCodeSequence))) == []


def test_wrong_instance_and_disabled_actor_do_not_write(target):
    with pytest.raises(ValueError, match='身份不匹配'):
        demo.import_materials(target, 1, 'other-instance')
    with orm_session(write=True) as db:
        db.get(User, 1).is_active = 0
    with pytest.raises(ValueError, match='现有管理员'):
        demo.import_materials(target, 1, instance_id())
    with orm_session() as db:
        assert list(db.scalars(select(Material))) == []


def test_non_demo_part_conflict_rolls_back_without_overwrite(target):
    with orm_session(write=True) as db:
        db.add(Material(sku='OLD-001', name='原有物料', unit='件',
            manufacturer_part_number=target[-1].manufacturer_part_number))
    with pytest.raises(ValueError, match='档案冲突'):
        demo.import_materials(target, 1, instance_id())
    with orm_session() as db:
        assert len(list(db.scalars(select(Material)))) == 1
        assert list(db.scalars(select(MaterialChange))) == []
        assert list(db.scalars(select(MaterialCodeSequence))) == []


def test_late_audit_failure_rolls_back_whole_batch_and_codes(target):
    def fail_late(db, *_):
        if any(isinstance(row, MaterialChange) and row.material_id == 49 for row in db.new):
            raise RuntimeError('模拟后段审计失败')
    event.listen(Session, 'before_flush', fail_late)
    try:
        with pytest.raises(RuntimeError, match='后段审计失败'):
            demo.import_materials(target, 1, instance_id())
    finally:
        event.remove(Session, 'before_flush', fail_late)
    with orm_session() as db:
        assert list(db.scalars(select(Material))) == []
        assert list(db.scalars(select(MaterialChange))) == []
        assert list(db.scalars(select(MaterialCodeSequence))) == []
    assert demo.import_materials(target, 1, instance_id())['created'] == 50
