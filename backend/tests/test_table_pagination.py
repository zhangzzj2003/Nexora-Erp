"""真实服务端分页、权限先过滤、字面搜索及快照隔离回归；本轮末统一运行。"""
from fastapi.testclient import TestClient
from app.main import app
from app.core.orm import orm_session
from app.core.models import Material
from app.query.snapshots import create_snapshot


def test_database_pages_filters_and_bounds(monkeypatch,tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH',str(tmp_path/'pages.db'))
    with TestClient(app,client=('127.0.0.1',12345)) as client:
        base='/api/v1'
        client.post(base+'/setup/admin',json={'username':'admin','password':'admin-password-123'})
        token=client.post(base+'/auth/login',json={'username':'admin','password':'admin-password-123'}).json()['token']
        headers={'Authorization':'Bearer '+token}
        with orm_session(write=True) as db:
            db.add_all([Material(sku=f'M{i:03}',name=f'物料{i:03}',unit='件') for i in range(125)])
        query={'dataset':'materials','query':'','page':3,'page_size':20,'sort':'sku','descending':False}
        result=client.post(base+'/tables/query',headers=headers,json=query)
        assert result.status_code==200,result.text
        page=result.json()
        assert page['total']==125 and len(page['items'])==20
        assert page['items'][0]['sku']=='M040' and page['items'][-1]['sku']=='M059'
        end=client.post(base+'/tables/query',headers=headers,json={**query,'page':999}).json()
        assert end['page']==7 and len(end['items'])==5
        empty=client.post(base+'/tables/query',headers=headers,json={**query,'query':'%_'}).json()
        assert empty['total']==0 and empty['items']==[]
        for bad in ({'page_size':101},{'page':0},{'dataset':'auth_sessions'},{'sort':'password_hash'},{'filters':{'password_hash':'x'}}):
            assert client.post(base+'/tables/query',headers=headers,json={**query,**bad}).status_code==422
        assert client.post(base+'/tables/query',json=query).status_code==401


def test_customer_count_is_scoped_before_pagination(monkeypatch,tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH',str(tmp_path/'scope.db'))
    with TestClient(app,client=('127.0.0.1',12345)) as client:
        base='/api/v1'
        client.post(base+'/setup/admin',json={'username':'admin','password':'admin-password-123'})
        def login(name):
            return {'Authorization':'Bearer '+client.post(base+'/auth/login',json={'username':name,'password':name+'-password-123'}).json()['token']}
        admin=login('admin')
        for name in ('alice','bob'):
            client.post(base+'/users',headers=admin,json={'username':name,'password':name+'-password-123','roles':['seller']})
        alice,bob=login('alice'),login('bob')
        for i in range(3):client.post(base+'/customers',headers=alice,json={'name':'甲客户'+str(i)})
        client.post(base+'/customers',headers=bob,json={'name':'乙客户'})
        query={'dataset':'customers','query':'','page':1,'page_size':2}
        own=client.post(base+'/tables/query',headers=alice,json=query).json()
        assert own['total']==3 and len(own['items'])==2
        assert all(row['name'].startswith('甲') for row in own['items'])
        assert client.post(base+'/tables/query',headers=admin,json=query).json()['total']==4
        assert client.post(base+'/tables/query',headers=alice,json={**query,'query':'乙客户'}).json()['total']==0


def test_snapshot_pages_keep_totals_and_refuse_other_users(monkeypatch,tmp_path):
    monkeypatch.setenv('NEXORA_DB_PATH',str(tmp_path/'snap.db'))
    with TestClient(app,client=('127.0.0.1',12345)) as client:
        base='/api/v1'
        client.post(base+'/setup/admin',json={'username':'admin','password':'admin-password-123'})
        def login(name):
            return {'Authorization':'Bearer '+client.post(base+'/auth/login',json={'username':name,'password':name+'-password-123'}).json()['token']}
        admin=login('admin')
        user=client.get(base+'/auth/me',headers=admin).json()
        snapshot=create_snapshot({'rows':[{'id':i,'balance':str(i+100)} for i in range(45)],'totals':{'amount':'999'},'csv':'完整导出'},user)
        query={'dataset':'snapshot','query':'','page':2,'page_size':20,'snapshot_id':snapshot}
        result=client.post(base+'/tables/query',headers=admin,json=query).json()
        assert result['total']==45 and result['items'][0]['balance']=='120'
        assert client.post(base+'/tables/snapshot-csv',headers=admin,json={'snapshot_id':snapshot}).json()['csv']=='完整导出'
        client.post(base+'/users',headers=admin,json={'username':'viewer','password':'viewer-password-123','roles':['viewer']})
        viewer=login('viewer')
        assert client.post(base+'/tables/query',headers=viewer,json=query).status_code==409
        assert client.post(base+'/tables/snapshot-csv',headers=viewer,json={'snapshot_id':snapshot}).status_code==409
        assert client.post(base+'/tables/query',headers=admin,json={**query,'snapshot_path':'__class__'}).status_code==422
