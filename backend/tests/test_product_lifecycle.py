"""系列与子机型软删除、停启、历史保留及并发写入的真实接口回归。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.catalog import products as product_routes
from app.core.database import connection, migrate
from app.core.models import Material, ProductChange, ProductModel, ProductProfile
from app.core.orm import orm_session
from test_products import erp, material


def series(req, code='LIFECYCLE'):
    """通过正式接口建立系列，避免测试绕过权限及审计。"""
    response = req('POST', '/product-models', {'code': code, 'name': code + ' 系列'})
    assert response.status_code == 201, response.text
    return response.json()


def product(req, code='BOARD', model_id=None, **fields):
    """使用唯一物料身份创建子机型，调用方可指定业务用途。"""
    response = req('POST', '/products', {'material': material(code), 'kind': 'semi_finished',
        'model_id': model_id, 'configuration_name': '标准板', **fields})
    assert response.status_code == 201, response.text
    return response.json()


def recipe(req, row, code='RAW'):
    """创建并启用真实配方，供工单和上层引用验证。"""
    raw = req('POST', '/materials', material(code)).json()
    response = req('POST', '/boms', {'product_material_id': row['material_id'],
        'lines': [{'component_material_id': raw['id'], 'quantity': '2'}]})
    assert response.status_code == 201, response.text
    bom = response.json()
    assert req('POST', f"/boms/{bom['id']}/activate").status_code == 200
    return req('GET', f"/boms/{bom['id']}").json()


def usage_change(row, enabled):
    """用途停启沿用联合编辑协议，完整带回归组、分类和其他用途。"""
    return {key: row[key] for key in ('kind', 'model_id', 'configuration_name', 'can_sell', 'can_purchase', 'version')} | {
        'can_produce': enabled, 'reason': '恢复生产' if enabled else '暂停新生产'}


def test_series_delete_checks_all_children_including_disabled_and_unfiltered_rows(erp):
    req, _, _ = erp
    model = series(req)
    # 搜索和分页只能限制展示，停用子机型仍属于系列，不能绕过完整关联检查。
    first = product(req, 'HIDDEN-A', model['id'], can_produce=False)
    second = product(req, 'HIDDEN-B', model['id'])
    assert req('POST', '/products/query', {'query': '不存在的产品', 'model_id': model['id']}).json()['total'] == 0
    assert req('POST', '/products/query', {'page_size': 1, 'model_id': model['id']}).json()['total'] == 2
    listed = next(row for row in req('GET', '/product-models').json() if row['id'] == model['id'])
    assert listed['child_count'] == 2
    blocked = req('DELETE', f"/product-models/{model['id']}", {'version': 1, 'reason': '清理系列'})
    assert blocked.status_code == 409 and '先删除子机型' in blocked.json()['detail']
    assert '2' in blocked.json()['detail']
    assert req('GET', f"/product-models/{model['id']}").json()['deleted_at'] is None
    for row in (first, second):
        deleted = req('DELETE', f"/products/{row['id']}", {'version': 1, 'reason': '停产归档'})
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()['deleted_at'] and deleted.json()['can_produce'] is False
    assert req('GET', '/product-models').json()[0]['child_count'] == 0
    removed = req('DELETE', f"/product-models/{model['id']}", {'version': 1, 'reason': '清理空系列'})
    assert removed.status_code == 200, removed.text
    assert removed.json()['version'] == 2 and removed.json()['deleted_by'] == model['created_by']
    assert removed.json()['deletion_reason'] == '清理空系列'
    assert req('GET', '/product-models').json() == []
    # 删除事实和审计仍能读取；编码保持占用，不能让旧引用指向后来新建的系列。
    retained = req('GET', f"/product-models/{model['id']}").json()
    assert retained['deleted_at'] == removed.json()['deleted_at'] and retained['child_count'] == 0
    history = req('GET', f"/product-models/{model['id']}/changes").json()
    assert history[0]['before']['deleted_at'] is None and history[0]['after']['deleted_at']
    assert req('POST', '/product-models', {'code': model['code'], 'name': '同编码新系列'}).status_code == 409


def test_deleted_model_rejects_new_and_changed_children_without_partial_material_writes(erp):
    req, _, _ = erp
    model = series(req)
    row = product(req)
    assert req('DELETE', f"/product-models/{model['id']}", {'version': 1, 'reason': '空系列删除'}).status_code == 200
    before = req('GET', '/materials').json()
    create = req('POST', '/products', {'model_id': model['id'], 'material': material('SHOULD-ROLLBACK')})
    assert create.status_code == 422 and '已删除' in create.json()['detail']
    assert req('GET', '/materials').json() == before
    update = req('PUT', f"/products/{row['id']}", {**usage_change(row, True), 'model_id': model['id'],
        'material': {**material('BOARD', '不应写入的新名称'), 'version': row['material']['version']}})
    assert update.status_code == 422
    current = req('GET', f"/products/{row['id']}").json()
    assert current['version'] == 1 and current['model_id'] is None
    assert current['material']['name'] == row['material']['name']
    assert req('PUT', f"/product-models/{model['id']}", {**model, 'version': 2,
        'name': '迟到的旧窗口', 'reason': '不允许恢复删除项'}).status_code == 404


def test_product_soft_delete_preserves_material_stock_bom_orders_and_audit(erp):
    req, reader, _ = erp
    row = product(req, can_sell=False, can_purchase=False)
    bom = recipe(req, row)
    draft = req('POST', '/boms', {'product_material_id': row['material_id'],
        'lines': [{'component_material_id': bom['lines'][0]['component_material_id'], 'quantity': '3'}]}).json()
    order_payload = {'bom_id': bom['id'], 'warehouse_id': 1, 'target_quantity': '3'}
    order_response = req.plan_work_order(order_payload)
    assert order_response.status_code == 201, order_response.text
    order = order_response.json()
    stock = req('GET', '/stock').json()
    material_before = req('GET', f"/materials/{row['material_id']}").json()
    removed = req('DELETE', f"/products/{row['id']}", {'version': 1, 'reason': '旧板卡归档'})
    assert removed.status_code == 200, removed.text
    assert removed.json()['version'] == 2 and removed.json()['deletion_reason'] == '旧板卡归档'
    assert removed.json()['deleted_by'] == row['created_by']
    assert removed.json()['can_produce'] is False and removed.json()['can_sell'] is False
    assert removed.json()['can_purchase'] is False
    assert req('GET', f"/products/{row['id']}").status_code == 404
    assert req('POST', '/products/query', {}).json()['total'] == 0
    assert req('GET', f"/materials/{row['material_id']}").json() == material_before
    assert req('GET', '/stock').json() == stock
    current_bom = req('GET', f"/boms/{bom['id']}").json()
    assert current_bom['status'] == bom['status'] == 'active'
    assert current_bom['lines'] == bom['lines'] and current_bom['product_can_produce'] is False
    assert next(item for item in req('GET', '/work-orders').json() if item['id'] == order['id']) == order
    assert req.plan_work_order(order_payload).status_code == 409
    assert req('POST', '/boms', {'product_material_id': row['material_id'],
        'lines': [{'component_material_id': bom['lines'][0]['component_material_id'], 'quantity': '1'}]}).status_code == 409
    activation = req('POST', f"/boms/{draft['id']}/activate")
    assert activation.status_code == 409 and '已删除' in activation.json()['detail']
    assert req('GET', f"/boms/{draft['id']}").json()['status'] == 'draft'
    assert req('POST', '/products', {'material_id': row['material_id']}).status_code == 409
    assert req('POST', '/materials', material('BOARD')).status_code == 409
    assert req('PUT', f"/products/{row['id']}", {**usage_change(row, True), 'version': 2}).status_code == 404
    changes = req('GET', f"/products/{row['id']}/changes", actor=reader)
    assert changes.status_code == 200, changes.text
    assert changes.json()[0]['before']['deleted_at'] is None
    assert changes.json()[0]['after']['deleted_at'] == removed.json()['deleted_at']
    assert changes.json()[0]['reason'] == '旧板卡归档'


def test_product_production_disable_and_reenable_preserve_profile_recipe_and_old_order(erp):
    req, _, _ = erp
    model = series(req)
    row = product(req, model_id=model['id'], can_sell=False, can_purchase=False)
    bom = recipe(req, row)
    payload = {'bom_id': bom['id'], 'warehouse_id': 1, 'target_quantity': '2'}
    original = req.plan_work_order(payload).json()
    disabled = req('PUT', f"/products/{row['id']}", usage_change(row, False))
    assert disabled.status_code == 200, disabled.text
    disabled = disabled.json()
    for key in ('material', 'kind', 'model_id', 'configuration_name', 'can_sell', 'can_purchase'):
        assert disabled[key] == row[key]
    assert disabled['can_produce'] is False and disabled['deleted_at'] is None
    assert req('POST', '/products/query', {}).json()['total'] == 1
    assert req('GET', '/product-models').json()[0]['child_count'] == 1
    assert req('GET', f"/boms/{bom['id']}").json()['status'] == 'active'
    blocked = req.plan_work_order(payload)
    assert blocked.status_code == 409 and '未允许生产' in blocked.json()['detail']
    assert next(item for item in req('GET', '/work-orders').json() if item['id'] == original['id']) == original
    resumed = req('PUT', f"/products/{row['id']}", usage_change(disabled, True))
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()['can_produce'] is True and resumed.json()['version'] == 3
    assert req.plan_work_order(payload).status_code == 201
    audit = req('GET', f"/products/{row['id']}/changes").json()
    assert audit[0]['before']['can_produce'] is False and audit[0]['after']['can_produce'] is True
    assert audit[1]['before']['can_produce'] is True and audit[1]['after']['can_produce'] is False


def test_disabled_child_stays_available_as_existing_inventory_component_of_parent(erp):
    req, _, _ = erp
    child = product(req)
    child_bom = recipe(req, child)
    parent = product(req, 'PARENT')
    parent_bom = req('POST', '/boms', {'product_material_id': parent['material_id'], 'lines': [
        {'component_material_id': child['material_id'], 'component_bom_id': child_bom['id'], 'quantity': '1'}]}).json()
    assert req('POST', f"/boms/{parent_bom['id']}/activate").status_code == 200
    assert req('PUT', f"/products/{child['id']}", usage_change(child, False)).status_code == 200
    # 停用仅禁止半成品自身的新生产，上层工单仍只按第一层组件领用其现有库存。
    parent_order = req.plan_work_order({'bom_id': parent_bom['id'], 'warehouse_id': 1, 'target_quantity': '2'})
    assert parent_order.status_code == 201, parent_order.text
    assert len(parent_order.json()['lines']) == 1
    assert parent_order.json()['lines'][0]['component_material_id'] == child['material_id']
    assert parent_order.json()['lines'][0]['required_quantity'] == '2.000'
    assert req('GET', f"/boms/{child_bom['id']}").json()['status'] == 'active'
    assert req.plan_work_order({'bom_id': child_bom['id'], 'warehouse_id': 1, 'target_quantity': '1'}).status_code == 409


def test_active_parent_fixed_recipe_blocks_product_delete_until_parent_retired(erp):
    req, _, _ = erp
    child = product(req)
    bom = recipe(req, child)
    parent = product(req, 'ASSEMBLY')
    response = req('POST', '/boms', {'product_material_id': parent['material_id'], 'lines': [
        {'component_material_id': child['material_id'], 'component_bom_id': bom['id'], 'quantity': '1'}]})
    assert response.status_code == 201, response.text
    parent_bom = response.json()
    draft_parent = req('POST', '/boms', {'product_material_id': parent['material_id'], 'lines': [
        {'component_material_id': child['material_id'], 'component_bom_id': bom['id'], 'quantity': '2'}]}).json()
    assert req('POST', f"/boms/{parent_bom['id']}/activate").status_code == 200
    blocked = req('DELETE', f"/products/{child['id']}", {'version': 1, 'reason': '准备删除'})
    assert blocked.status_code == 409 and '上层 BOM' in blocked.json()['detail']
    assert req('GET', f"/products/{child['id']}").json()['version'] == 1
    assert req('POST', f"/boms/{parent_bom['id']}/retire").status_code == 200
    assert req('DELETE', f"/products/{child['id']}", {'version': 1, 'reason': '上层已停用'}).status_code == 200
    assert req('GET', f"/boms/{parent_bom['id']}").json()['lines'][0]['component_bom_id'] == bom['id']
    activation = req('POST', f"/boms/{draft_parent['id']}/activate")
    assert activation.status_code == 422 and '已删除' in activation.json()['detail']
    # 历史固定引用可读，但新建上层配方不得继续引用已删除子机型的生产配方。
    assert req('POST', '/boms', {'product_material_id': parent['material_id'], 'lines': [
        {'component_material_id': child['material_id'], 'component_bom_id': bom['id'], 'quantity': '1'}]}).status_code == 422


def test_deleted_parent_recipe_does_not_block_child_cleanup_or_erase_existing_mrp_supply(erp):
    req, _, _ = erp
    model = series(req)
    child = product(req, 'ARCHIVE-BOARD', model['id'])
    child_bom = recipe(req, child, 'ARCHIVE-RAW')
    parent = product(req, 'ARCHIVE-FINAL', model['id'])
    response = req('POST', '/boms', {'product_material_id': parent['material_id'], 'lines': [
        {'component_material_id': child['material_id'], 'component_bom_id': child_bom['id'], 'quantity': '1'}]})
    assert response.status_code == 201, response.text
    parent_bom = response.json()
    assert req('POST', f"/boms/{parent_bom['id']}/activate").status_code == 200
    parent_bom = req('GET', f"/boms/{parent_bom['id']}").json()
    orders = []
    for bom in (child_bom, parent_bom):
        response = req.plan_work_order({'bom_id': bom['id'], 'warehouse_id': 1, 'target_quantity': '2'})
        assert response.status_code == 201, response.text
        orders.append(response.json())
    source = req('GET', '/production/mrp/options')
    assert source.status_code == 200, source.text
    before = source.json()
    assert len(before['boms']) == 2 and len(before['supplies']) == len(before['reservations']) == 2

    # 仅停用上层产品时，仍须保护其启用配方的固定引用；软删除后才成为历史配方。
    stopped = req('PUT', f"/products/{parent['id']}", usage_change(parent, False))
    assert stopped.status_code == 200, stopped.text
    blocked = req('DELETE', f"/products/{child['id']}", {'version': 1, 'reason': '应由上层引用阻止'})
    assert blocked.status_code == 409 and '上层 BOM' in blocked.json()['detail']
    assert req('DELETE', f"/products/{parent['id']}", {'version': 2, 'reason': '成品整体归档'}).status_code == 200
    intermediate = req('GET', '/production/mrp/options')
    assert intermediate.status_code == 200, intermediate.text
    assert [row['id'] for row in intermediate.json()['boms']] == [child_bom['id']]
    assert intermediate.json()['supplies'] == before['supplies']
    assert intermediate.json()['reservations'] == before['reservations']
    assert req('DELETE', f"/products/{child['id']}", {'version': 1, 'reason': '半成品随系列归档'}).status_code == 200
    assert req('DELETE', f"/product-models/{model['id']}", {'version': 1, 'reason': '所有子机型均已归档'}).status_code == 200
    assert req('GET', '/product-models').json() == []
    assert req('POST', '/products/query', {}).json()['total'] == 0

    # 不改写已发布配方和历史工单，只从可新生产配方中排除已删产品。
    for bom in (child_bom, parent_bom):
        preserved = req('GET', f"/boms/{bom['id']}").json()
        assert preserved['status'] == bom['status'] == 'active'
        assert preserved['lines'] == bom['lines']
    current_orders = req('GET', '/work-orders').json()
    for order in orders:
        assert next(row for row in current_orders if row['id'] == order['id']) == order
    current_source = req('GET', '/production/mrp/options')
    assert current_source.status_code == 200, current_source.text
    after = current_source.json()
    assert after['boms'] == []
    # 尚未完成的旧工单仍代表真实供给和材料预约，不能随产品隐藏而从 MRP 消失。
    assert after['supplies'] == before['supplies']
    assert after['reservations'] == before['reservations']


def test_deleted_product_historical_recipe_does_not_form_false_cycle_for_plain_stock_component(erp):
    req, _, _ = erp
    child = product(req, 'CYCLE-CHILD')
    child_bom = recipe(req, child, 'CYCLE-RAW')
    parent = product(req, 'CYCLE-PARENT')
    response = req('POST', '/boms', {'product_material_id': parent['material_id'], 'lines': [
        {'component_material_id': child['material_id'], 'component_bom_id': child_bom['id'], 'quantity': '1'}]})
    assert response.status_code == 201, response.text
    parent_bom = response.json()
    assert req('POST', f"/boms/{parent_bom['id']}/activate").status_code == 200
    assert req('POST', f"/boms/{child_bom['id']}/retire").status_code == 200
    # 展示中的下层状态会跟随显式停用变化，在删除前记录实际历史内容再比较。
    parent_bom = req('GET', f"/boms/{parent_bom['id']}").json()
    revised = req('POST', '/boms', {'product_material_id': child['material_id'], 'lines': [
        {'component_material_id': parent['material_id'], 'quantity': '1'}]})
    assert revised.status_code == 201, revised.text
    revised = revised.json()

    # 未删除或仅停用的上层配方仍进入循环检测，不能借生产用途开关绕过保护。
    for stopped in (False, True):
        if stopped:
            assert req('PUT', f"/products/{parent['id']}", usage_change(parent, False)).status_code == 200
        blocked = req('POST', f"/boms/{revised['id']}/activate")
        assert blocked.status_code == 409 and '循环引用' in blocked.json()['detail']
    assert req('DELETE', f"/products/{parent['id']}", {'version': 2, 'reason': '旧总成归档'}).status_code == 200

    # 上层产品已删除后，其历史配方不再制造虚假环；保留物料可作为普通库存组件使用。
    activated = req('POST', f"/boms/{revised['id']}/activate")
    assert activated.status_code == 200, activated.text
    assert activated.json()['lines'][0]['component_material_id'] == parent['material_id']
    assert activated.json()['lines'][0]['component_bom_id'] is None
    preserved = req('GET', f"/boms/{parent_bom['id']}").json()
    assert preserved['status'] == 'active' and preserved['lines'] == parent_bom['lines']
    source = req('GET', '/production/mrp/options')
    assert source.status_code == 200, source.text
    assert [row['id'] for row in source.json()['boms']] == [revised['id']]
    # 库存身份保留不代表允许重新挂接已删产品的固定生产配方。
    invalid = req('POST', '/boms', {'product_material_id': child['material_id'], 'lines': [
        {'component_material_id': parent['material_id'], 'component_bom_id': parent_bom['id'], 'quantity': '1'}]})
    assert invalid.status_code == 422 and '已删除' in invalid.json()['detail']


@pytest.mark.parametrize('entity', ['product-models', 'products'])
def test_delete_requires_permission_reason_current_version_and_cannot_repeat(erp, entity):
    req, reader, planner = erp
    row = series(req) if entity == 'product-models' else product(req)
    path = f"/{entity}/{row['id']}"
    payload = {'version': 1, 'reason': '清理测试资料'}
    for actor in (reader, planner):
        assert req('DELETE', path, payload, actor=actor).status_code == 403
    for reason in ('', '   '):
        assert req('DELETE', path, {**payload, 'reason': reason}).status_code == 422
    for version in (0, '1', True):
        assert req('DELETE', path, {**payload, 'version': version}).status_code == 422
    assert req('DELETE', path, {**payload, 'version': 2}).status_code == 409
    assert req('GET', path).json()['version'] == 1
    assert len(req('GET', path + '/changes').json()) == 1
    assert req('DELETE', path, payload).status_code == 200
    assert req('DELETE', path, {**payload, 'version': 2}).status_code == 404
    assert len(req('GET', path + '/changes').json()) == 2


@pytest.mark.parametrize('entity,kind', [('product-models', 'model'), ('products', 'product')])
def test_soft_delete_and_audit_failure_rollback_as_one_transaction(erp, monkeypatch, entity, kind):
    req, _, _ = erp
    row = series(req) if kind == 'model' else product(req)
    path = f"/{entity}/{row['id']}"

    def fail_audit(*_args, **_kwargs):
        # 删除列已 flush 后模拟审计写入失败，不能留下没有审计证据的删除事实。
        raise HTTPException(503, '模拟审计存储失败')

    monkeypatch.setattr(product_routes, 'product_change', fail_audit)
    assert req('DELETE', path, {'version': 1, 'reason': '失败应回滚'}).status_code == 503
    with orm_session() as db:
        current = db.get(ProductModel if kind == 'model' else ProductProfile, row['id'])
        assert current.deleted_at is None and current.deleted_by is None and current.version == 1
        assert db.scalar(select(func.count(ProductChange.id)).where(
            ProductChange.entity_kind == kind, ProductChange.entity_id == row['id'])) == 1
    assert req('GET', path).status_code == 200


def test_model_delete_and_new_child_are_serialized_without_orphaned_live_children(erp):
    req, _, _ = erp
    # 两个请求同时进入写边界；无论谁先拿到锁，都必须满足同一个系列关联不变量。
    for index in range(3):
        model = series(req, f'RACE-{index}')
        barrier = Barrier(2)

        def remove():
            barrier.wait(timeout=5)
            return req('DELETE', f"/product-models/{model['id']}", {'version': 1, 'reason': '并发删除空系列'})

        def create():
            barrier.wait(timeout=5)
            return req('POST', '/products', {'model_id': model['id'], 'material': material(f'RACE-{index}')})

        with ThreadPoolExecutor(max_workers=2) as executor:
            removed = executor.submit(remove)
            created = executor.submit(create)
            removed, created = removed.result(timeout=20), created.result(timeout=20)
        assert (removed.status_code, created.status_code) in ((200, 422), (409, 201)), (removed.text, created.text)
        with orm_session() as db:
            current = db.get(ProductModel, model['id'])
            child_count = db.scalar(select(func.count(ProductProfile.id)).where(
                ProductProfile.model_id == model['id'], ProductProfile.deleted_at.is_(None)))
            assert (current.deleted_at is None and child_count == 1) or (current.deleted_at is not None and child_count == 0)
            # 新建失败时，在同一事务内创建的物料也不能漏出来。
            assert db.scalar(select(func.count(Material.id)).where(Material.sku == f'PRODUCT-RACE-{index}')) == child_count


def test_105_upgrade_adds_soft_delete_columns_without_rewriting_existing_evidence(erp):
    req, _, _ = erp
    model = series(req)
    row = product(req, model_id=model['id'], can_sell=False)
    bom = recipe(req, row)
    order = req.legacy_work_order({'bom_id': bom['id'], 'warehouse_id': 1, 'target_quantity': '2'}).json()
    before_stock = req('GET', '/stock').json()
    product_history = req('GET', f"/products/{row['id']}/changes").json()
    model_history = req('GET', f"/product-models/{model['id']}/changes").json()
    # 真实模拟第 105 版缺列结构，连续迁移两次同时检查追加性与幂等性。
    with connection() as db:
        for table in ('product_models', 'product_profiles'):
            for column in ('deleted_at', 'deleted_by', 'deletion_reason'):
                db.execute(f'ALTER TABLE {table} DROP COLUMN {column}')
        db.execute('PRAGMA user_version = 105')
    migrate()
    migrate()
    current = req('GET', f"/products/{row['id']}").json()
    assert current == row
    assert req('GET', f"/product-models/{model['id']}").json()['deleted_at'] is None
    assert req('GET', f"/products/{row['id']}/changes").json() == product_history
    assert req('GET', f"/product-models/{model['id']}/changes").json() == model_history
    assert req('GET', f"/boms/{bom['id']}").json() == bom
    assert req('GET', '/stock').json() == before_stock
    assert next(item for item in req('GET', '/work-orders').json() if item['id'] == order['id']) == order
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 111
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
