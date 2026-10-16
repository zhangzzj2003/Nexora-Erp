"""产品专用表单省略采购及元件字段时，真实接口保留既有物料资料。"""

import json

import pytest
from sqlalchemy import select

from app.core.models import MaterialChange
from app.core.orm import orm_session
from test_products import erp


HIDDEN_DETAILS = {
    'package': '历史封装资料',
    'brand': '原制造商',
    'manufacturer_part_number': 'ORIGINAL-900',
    'electrical_value': '12V',
    'tolerance': '±1%',
    'rated_voltage': '24V',
    'rated_power': '60W',
    'temperature_range': '-20～70℃',
    'compliance': 'RoHS',
    'extra_attributes': [{'name': '历史定制工艺', 'value': '阳极氧化', 'unit': ''}],
}


def category_with_required_spec(req):
    # 自定义成品类别，确保校验来自真实模板，而非电子类固定字段。
    for code, parent, name in [('PF', None, '测试成品'), ('PF-UT', 'PF', '测试整机')]:
        result = req('POST', '/material-categories', {
            'code': code, 'parent_code': parent, 'name': name,
        })
        assert result.status_code == 201, result.text
    child = next(row for group in req('GET', '/material-categories').json()
                 for row in group['children'] if row['code'] == 'PF-UT')
    result = req('POST', '/material-categories/PF-UT/fields', {
        'version': child['version'], 'reason': '按整机参数建立模板',
        'name': '额定载荷', 'kind': 'number', 'unit': 'kg', 'required': True,
    })
    assert result.status_code == 201, result.text
    return result.json()


def product_material_changes(material_id):
    # 审计没有物料独立查询接口；通过 ORM 读取事务结果，仍由真实 API 完成业务写入。
    with orm_session() as db:
        return [{'before': json.loads(row.before_json) if row.before_json else None,
                 'after': json.loads(row.after_json), 'reason': row.reason}
                for row in db.scalars(select(MaterialChange)
                    .where(MaterialChange.material_id == material_id)
                    .order_by(MaterialChange.id))]


def test_product_visible_edit_preserves_hidden_details_and_all_supplier_links(erp):
    req, _, _ = erp
    category = category_with_required_spec(req)
    field = category['fields'][-1]
    created = req('POST', '/products', {
        'kind': 'finished', 'configuration_name': '标准版',
        'material': {
            'name': '原整机', 'unit': '台', 'category_code': 'PF-UT',
            'specification': '原整机规格', 'notes': '原备注',
            'spec_template_version': category['template_version'],
            'spec_values': [{'field_id': field['id'], 'status': 'filled',
                             'value': '25.5', 'source': '原图纸'}],
            **HIDDEN_DETAILS,
        },
    })
    assert created.status_code == 201, created.text
    original = created.json()
    product_id, material_id = original['id'], original['material_id']
    supplier_ids = []
    # 独立绑定接口可累计超过表单批量绑定的 20 家限制；产品编辑不应重提或截断它们。
    for index in range(21):
        supplier = req('POST', '/suppliers', {'name': f'历史整机供应商{index:02d}'})
        assert supplier.status_code == 201, supplier.text
        supplier_ids.append(supplier.json()['id'])
        linked = req('PUT', f'/suppliers/{supplier_ids[-1]}/materials/{material_id}')
        assert linked.status_code == 204, linked.text
    before = req('GET', f'/products/{product_id}').json()
    assert before['material']['supplier_ids'] == supplier_ids
    assert before['material']['version'] == 22
    material_history = product_material_changes(material_id)
    supplier_history = req('GET', '/supplier-changes').json()

    saved = req('PUT', f'/products/{product_id}', {
        'kind': 'finished', 'configuration_name': '升级版',
        'version': before['version'], 'reason': '更正整机名称与规格',
        'material': {
            'name': '更新整机', 'unit': '台', 'category_code': 'PF-UT',
            'specification': '整机新版规格', 'notes': '更新备注',
            'version': before['material']['version'], 'reason': '产品页面更正资料',
        },
    })
    assert saved.status_code == 200, saved.text
    after = saved.json()
    assert (after['version'], after['material']['version']) == (2, 23)
    assert after['configuration_name'] == '升级版'
    assert after['material']['name'] == '更新整机'
    assert after['material']['specification'] == '整机新版规格'
    assert after['material']['notes'] == '更新备注'
    for key in (*HIDDEN_DETAILS, 'spec_values', 'spec_template_version', 'supplier_ids'):
        assert after['material'][key] == before['material'][key]
    assert after['material']['sku'] == before['material']['sku']
    assert req('GET', f'/materials/{material_id}?include_suppliers=true').json() == after['material']
    assert len(req('GET', '/suppliers').json()) == 21
    assert req('GET', '/supplier-changes').json() == supplier_history
    assert {row['supplier_id'] for row in req('GET', '/supplier-materials').json()
            if row['material_id'] == material_id} == set(supplier_ids)

    product_history = req('GET', f'/products/{product_id}/changes').json()
    assert len(product_history) == 2
    assert product_history[0]['before'] == before
    assert product_history[0]['after'] == after
    assert product_history[0]['reason'] == '更正整机名称与规格'
    changes = product_material_changes(material_id)
    assert changes[:-1] == material_history
    assert changes[-1]['reason'] == '产品页面更正资料'
    assert changes[-1]['before']['version'] == 22
    assert changes[-1]['after']['version'] == 23
    for key in (*HIDDEN_DETAILS, 'spec_values'):
        assert changes[-1]['before'][key] == before['material'][key]
        assert changes[-1]['after'][key] == before['material'][key]


@pytest.mark.parametrize('kind', ['finished', 'semi_finished', 'component'])
def test_new_product_without_procurement_or_component_fields_is_valid(erp, kind):
    req, _, _ = erp
    # 成品、半成品与组件都只提交可见的通用资料；数据库默认空资料不构成额外必填项。
    response = req('POST', '/products', {
        'kind': kind, 'configuration_name': '标准版',
        'material': {'name': '新子机型', 'unit': '台', 'category_code': 'EL-PC',
                     'specification': '通用整机规格', 'notes': '产品说明'},
    })
    assert response.status_code == 201, response.text
    row = response.json()
    assert row['kind'] == kind
    assert row['version'] == row['material']['version'] == 1
    assert row['material']['supplier_ids'] == []
    assert all(row['material'][key] == '' for key in HIDDEN_DETAILS if key != 'extra_attributes')
    assert row['material'].get('extra_attributes', []) == []
    assert req('GET', '/suppliers').json() == []
    assert req('GET', f"/products/{row['id']}").json() == row


def test_required_category_specs_still_reject_invalid_product_create_and_edit_atomically(erp):
    req, _, _ = erp
    category = category_with_required_spec(req)
    field = category['fields'][-1]
    minimal = {'name': '缺少规格整机', 'unit': '台', 'category_code': 'PF-UT'}
    # 隐藏固定元件字段不等于绕过当前分类的必填模板。
    missing = req('POST', '/products', {'kind': 'finished', 'material': minimal})
    assert missing.status_code == 422, missing.text
    assert '额定载荷' in missing.json()['detail']
    assert req('GET', '/materials').json() == []
    assert req('POST', '/products/query', {}).json()['total'] == 0
    created = req('POST', '/products', {
        'kind': 'semi_finished', 'configuration_name': '旧配置',
        'material': {'name': '原有板卡', 'unit': '台', 'category_code': 'EL-PC',
                     **HIDDEN_DETAILS},
    })
    assert created.status_code == 201, created.text
    before = created.json()
    path = f"/products/{before['id']}"
    product_history = req('GET', path + '/changes').json()
    material_history = product_material_changes(before['material_id'])
    update = {'kind': 'finished', 'configuration_name': '不能只保存归组',
              'version': before['version'], 'reason': '改为整机',
              'material': {**minimal, 'version': before['material']['version']}}
    for values in (None, [], [{'field_id': field['id'], 'status': 'unknown', 'value': None}]):
        payload = {**update, 'material': dict(update['material'])}
        if values is not None:
            payload['material'].update(spec_values=values, spec_template_version=category['template_version'])
        response = req('PUT', path, payload)
        assert response.status_code == 422, response.text
        assert '额定载荷' in response.json()['detail']
        assert req('GET', path).json() == before
        assert req('GET', path + '/changes').json() == product_history
        assert product_material_changes(before['material_id']) == material_history
