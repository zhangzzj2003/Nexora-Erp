"""预警按仓库精确计算，修订冲突、授权、审计及迁移不得破坏原业务。"""

import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.main import app
from app.core.database import migrate
from app.core.models import Base, InventoryWarningRule, InventoryWarningChange
from app.core.orm import orm_session

ROOT = 'inventory/warnings'


@pytest.fixture
def erp(monkeypatch, tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH', str(tmp_path / 'warnings.db'))
    with TestClient(app, client=('127.0.0.1',12000), raise_server_exceptions=False) as client:
        actors = {}
        def api(method, path, payload=None, actor='admin', status=200):
            response = client.request(method, '/api/v1/' + path, json=payload, headers=actors.get(actor, {}))
            assert response.status_code == status, response.text
            return response.json() if status not in (204,500) else None
        def login(name):
            token = api('POST','auth/login',{'username':name,'password':'secure-pass-123'})['token']
            return {'Authorization':'Bearer '+token}
        api('POST','setup/admin',{'username':'admin','password':'secure-pass-123'},status=201)
        actors['admin'] = login('admin')
        api('POST','roles',{'code':'warning_writer','label':'仅配置权限','permissions':['inventory_warning.manage']},status=201)
        for name,role in (('viewer','viewer'),('warehouse','warehouse'),('writer','warning_writer'),('seller','seller')):
            api('POST','users',{'username':name,'password':'secure-pass-123','roles':[role]},status=201)
            actors[name] = login(name)
        material = api('POST','materials',{'sku':'ALERT-PART','name':'预警测试物料','unit':'件'},status=201)['id']
        warehouse = api('POST','warehouses',{'code':'SECOND','name':'第二仓库'},status=201)['id']
        yield client,api,actors,material,warehouse


def save(erp, warehouse=1, **extra):
    return erp[1]('PUT', ROOT+f'/rules/{warehouse}/{erp[3]}',
                  {**dict(version=0,threshold='1.000',enabled=True,reason='按本仓库备货规则'),**extra})


def inbound(erp, warehouse, quantity, post=True):
    api = erp[1]
    row = api('POST','warehouse-inbounds',{'warehouse_id':warehouse,'reason':'other','note':'预警来源',
              'lines':[{'material_id':erp[3],'quantity':quantity}]},status=201)
    if post:
        api('POST',f'warehouse-inbounds/{row["id"]}/post')
    return row


def test_exact_threshold_and_warehouse_scope_do_not_mask_shortages(erp):
    api = erp[1]
    save(erp,threshold='0.300')
    save(erp,warehouse=erp[4],threshold='0.300')
    inbound(erp,1,'0.100'); inbound(erp,1,'0.200'); inbound(erp,erp[4],'0.125')
    result = api('GET',ROOT)
    first,second = result['rows']
    assert first['quantity']=='0.300' and first['status']=='normal' and first['shortage']=='0'
    assert second['quantity']=='0.125' and second['status']=='low' and second['shortage']=='0.175'
    assert result['summary']==dict(normal=1,low=1,out_of_stock=0,disabled=0,configured=2,unconfigured=0)
    selected = api('GET',ROOT+f'?warehouse_id={erp[4]}')
    assert selected['warehouse_id']==erp[4] and len(selected['rows'])==1
    assert selected['rows'][0]==second
    assert selected['summary']['low']==1 and selected['summary']['normal']==0


def test_unconfigured_zero_threshold_disabled_and_draft_are_explicit(erp):
    api = erp[1]
    result = api('GET',ROOT)
    assert result['rows']==[] and result['summary']['unconfigured']==2
    inbound(erp,1,'10',post=False)
    detail = save(erp,threshold='0')
    assert detail['row']['quantity']=='0' and detail['row']['status']=='out_of_stock'
    assert detail['row']['threshold']=='0.000' and detail['row']['shortage']=='0'
    assert detail['changes'][0]['before'] is None and detail['changes'][0]['after']['enabled'] is True
    changed = save(erp,version=1,threshold='5',enabled=False,reason='停用本仓库规则')
    assert changed['row']['status']=='disabled' and changed['row']['shortage'] is None
    assert api('GET',ROOT)['summary']==dict(normal=0,low=0,out_of_stock=0,disabled=1,configured=1,unconfigured=1)


def test_confirmed_stock_and_reversal_change_alert_without_rewriting_rule(erp):
    api = erp[1]
    row = save(erp,threshold='1')
    received = inbound(erp,1,'1')
    assert api('GET',ROOT)['rows'][0]['status']=='normal'
    api('POST',f'warehouse-inbounds/{received["id"]}/reverse',{'reason':'更正误确认'},status=201)
    detail = api('GET',ROOT+f'/rules/1/{erp[3]}')
    assert detail['row']['status']=='out_of_stock' and detail['row']['quantity']=='0'
    assert detail['row']['version']==1 and detail['changes']==row['changes']


def test_negative_zero_threshold_is_canonical_for_desktop_validation(erp):
    detail = save(erp, threshold='-0.000')
    assert detail['row']['threshold'] == '0.000'
    assert detail['row']['status'] == 'out_of_stock'
    assert detail['changes'][0]['after']['threshold'] == '0.000'


def test_rule_conflict_preserves_previous_evidence_and_names_at_revision(erp):
    api = erp[1]
    first = save(erp)
    current = save(erp,version=1,threshold='2',reason='扩大储备')
    for version in (0,1):
        api('PUT',ROOT+f'/rules/1/{erp[3]}',dict(version=version,threshold='99',enabled=True,reason='过期正文'),status=409)
    assert api('GET',ROOT+f'/rules/1/{erp[3]}')==current
    api('PUT',f'materials/{erp[3]}',{'sku':'ALERT-PART','name':'改名物料','unit':'箱','version':1,'reason':'核对名称和单位'})
    later = save(erp,version=2,threshold='3',reason='核对新资料')
    assert later['row']['material_name']=='改名物料' and later['row']['unit']=='箱'
    assert later['changes'][0]['after']['sku']=='ALERT-PART'
    assert later['changes'][1]['before']==first['changes'][0]['after']
    assert later['changes'][2]['after']['material_name']=='改名物料'


def test_permissions_live_revocation_and_no_view_write_do_not_expose_data(erp):
    _,api,actors,material,warehouse = erp
    save(erp)
    assert api('GET',ROOT,actor='viewer')['rows'][0]['version']==1
    api('PUT',ROOT+f'/rules/1/{material}',dict(version=1,threshold='2',enabled=True,reason='越权'),actor='viewer',status=403)
    api('PUT',ROOT+f'/rules/{warehouse}/{material}',dict(version=0,threshold='2',enabled=True,reason='仓库制度'),actor='warehouse')
    api('GET',ROOT,actor='writer',status=403)
    api('PUT',ROOT+'/rules/999/999',dict(version=0,threshold='2',enabled=True,reason='无查看权限'),actor='writer',status=403)
    api('GET',ROOT,actor='anonymous',status=401)
    # 使用已有会话重新读取权限，角色撤权立即影响后续读取。
    api('PUT','roles/warning_writer',{'label':'撤权角色','permissions':[]})
    api('PUT',ROOT+f'/rules/1/{material}',dict(version=1,threshold='2',enabled=True,reason='撤权后写入'),actor='writer',status=403)


@pytest.mark.parametrize('invalid',[-1,'-0.001','1.0001','1000000.001','NaN','Infinity',True,0.1,None])
def test_bad_thresholds_never_create_a_rule(erp,invalid):
    api = erp[1]
    api('PUT',ROOT+f'/rules/1/{erp[3]}',dict(version=0,threshold=invalid,enabled=True,reason='错误输入'),status=422)
    assert api('GET',ROOT)['rows']==[]


@pytest.mark.parametrize('extra',[{'version':True},{'version':-1},{'version':1.1},{'enabled':1},{'reason':'  '},{'unknown':'忽略不得发生'}])
def test_strict_versions_enable_reason_and_field_whitelist(erp,extra):
    erp[1]('PUT',ROOT+f'/rules/1/{erp[3]}',{**dict(version=0,threshold='1',enabled=True,reason='登记'),**extra},status=422)


def test_missing_sources_bad_scope_and_reference_protection(erp):
    api = erp[1]
    api('GET',ROOT+'?warehouse_id=0',status=422)
    api('GET',ROOT+'?warehouse_id=999',status=404)
    api('GET',ROOT+f'/rules/1/{erp[3]}',status=404)
    for warehouse,material in ((999,erp[3]),(1,999)):
        api('PUT',ROOT+f'/rules/{warehouse}/{material}',dict(version=0,threshold='1',enabled=True,reason='登记'),status=404)
    save(erp,warehouse=erp[4],enabled=False)
    api('DELETE',f'materials/{erp[3]}',status=409)
    api('DELETE',f'warehouses/{erp[4]}?version=1',status=409)
    assert len(api('GET',ROOT)['rows'])==1


def test_concurrent_creation_and_revision_have_one_winner(erp):
    client,api,actors,material,_ = erp
    for version in (0,1):
        barrier = Barrier(2)
        def call(index):
            barrier.wait()
            return client.put('/api/v1/'+ROOT+f'/rules/1/{material}',headers=actors['admin'],
                json=dict(version=version,threshold=str(index+1),enabled=True,reason=f'并发修订 {index}')).status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            assert sorted(executor.map(call,range(2)))==[200,409]
    row = api('GET',ROOT+f'/rules/1/{material}')
    assert row['row']['version']==2 and len(row['changes'])==2


def test_failure_after_audit_flush_rolls_back_rule_and_revision(erp):
    api = erp[1]
    first = save(erp)
    def fail(session,_):
        if any(isinstance(row,InventoryWarningChange) for row in session.new):
            raise RuntimeError('模拟规则与审计写后故障')
    event.listen(Session,'after_flush',fail)
    try:
        api('PUT',ROOT+f'/rules/1/{erp[3]}',dict(version=1,threshold='9',enabled=False,reason='写后故障'),status=500)
        api('PUT',ROOT+f'/rules/{erp[4]}/{erp[3]}',dict(version=0,threshold='9',enabled=False,reason='写后故障'),status=500)
    finally:
        event.remove(Session,'after_flush',fail)
    assert api('GET',ROOT+f'/rules/1/{erp[3]}')==first
    assert len(api('GET',ROOT)['rows'])==1


def test_v54_upgrade_preserves_business_and_is_idempotent(erp,remove_inventory_warning_schema):
    inbound(erp,1,'0.125')
    erp[1]('PUT',f'materials/{erp[3]}',dict(name='已分类物料',unit='件',version=1,category_code='EL-SR',specification='10 kΩ',brand='测试品牌'))
    erp[1]('POST','materials',dict(name='自动编码物料',unit='件',category_code='EL-SR'),status=201)
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        material_before = db.execute('SELECT * FROM materials ORDER BY id').fetchall()
        codes_before = db.execute('SELECT * FROM material_code_sequences ORDER BY prefix').fetchall()
        changes_before = db.execute('SELECT * FROM material_changes ORDER BY id').fetchall()
        before = db.execute('SELECT * FROM stock_movements ORDER BY id').fetchall()
        remove_inventory_warning_schema(db);db.execute('PRAGMA user_version=54')
    migrate();migrate()
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]== 76
        assert db.execute('SELECT * FROM stock_movements ORDER BY id').fetchall()==before
        assert db.execute('SELECT * FROM materials ORDER BY id').fetchall()==material_before
        assert db.execute('SELECT * FROM material_code_sequences ORDER BY prefix').fetchall()==codes_before
        assert db.execute('SELECT * FROM material_changes ORDER BY id').fetchall()==changes_before
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
        assert db.execute("SELECT COUNT(*) FROM role_permissions WHERE permission_code='inventory_warning.manage'").fetchone()[0]==2
    assert len(Base.metadata.tables)== 174


@pytest.mark.parametrize('old_version',[53,54])
def test_failed_migration_leaves_no_partial_structure(erp,remove_inventory_warning_schema,remove_material_schema,monkeypatch,old_version):
    from app.core import database
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        (remove_material_schema if old_version==53 else remove_inventory_warning_schema)(db)
        db.execute(f'PRAGMA user_version={old_version}')
    original = database.connection
    @contextmanager
    def fail_structure():
        with original() as db:
            db.set_authorizer(lambda action,name,*_: sqlite3.SQLITE_DENY
                if action==sqlite3.SQLITE_CREATE_TABLE and name=='inventory_warning_changes' else sqlite3.SQLITE_OK)
            yield db
    with monkeypatch.context() as scoped:
        scoped.setattr(database,'connection',fail_structure)
        with pytest.raises(sqlite3.DatabaseError):migrate()
    with sqlite3.connect(os.environ['NEXORA_DB_PATH']) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==old_version
        assert ('category_code' in {row[1] for row in db.execute('PRAGMA table_info(materials)')}) == (old_version==54)
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='inventory_warning_rules'").fetchone()
    migrate()
