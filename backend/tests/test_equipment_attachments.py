"""设备及维护工单附件的权限、状态冻结与升级验证。"""

import base64
import hashlib

from app.core.database import connection, migrate
from app.core.models import Base, EquipmentAttachment, EquipmentAttachmentReversal
from app.core.orm import orm_session
from test_equipment import action, erp, job_input


PDF = b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n'


def payload(content=PDF, name='现场照片.pdf'):
    return {'file_name': name, 'content_base64': base64.b64encode(content).decode(),
            'reason': '现场记录 W-001'}


def path(kind, identifier):
    return f'equipment/{kind}/{identifier}/attachments'


def test_asset_and_job_keep_original_and_reversal(erp):
    client, api, actors, _, asset, _ = erp
    job = api('POST', 'equipment/jobs', job_input(erp), status=201)
    for kind, identifier in (('asset', asset['id']), ('job', job['id'])):
        base = path(kind, identifier)
        item = api('POST', base, payload(), actor='planner', status=201)
        assert item['entity_kind'] == kind and item['entity_id'] == identifier
        assert item['sha256'] == hashlib.sha256(PDF).hexdigest()
        assert 'content' not in item and item['reversal'] is None
        assert api('GET', base, actor='observer')['items'] == [item]
        download = client.get('/api/v1/'+base+f'/{item["id"]}', headers=actors['observer'])
        assert download.content == PDF and download.headers['cache-control'] == 'no-store'
        api('POST', base, payload(), status=409)
        reversed_item = api('POST', base+f'/{item["id"]}/reverse',
            {'reason': '上传的证据有误'}, actor='planner', status=201)
        assert reversed_item['reversal']['reason'] == '上传的证据有误'
        assert client.get('/api/v1/'+base+f'/{item["id"]}', headers=actors['admin']).content == PDF
        api('POST', base+f'/{item["id"]}/reverse', {'reason': '重复'}, status=409)
        assert api('POST', base, payload(), status=201)['id'] != item['id']
        with orm_session() as db:
            assert db.get(EquipmentAttachment, item['id']).content == PDF
            assert db.query(EquipmentAttachmentReversal).filter_by(attachment_id=item['id']).count() == 1
    assert api('GET', f'equipment/jobs/{job["id"]}')['version'] == job['version']


def test_limits_permissions_and_cross_record_path(erp):
    _, api, _, _, asset, _ = erp
    job = api('POST', 'equipment/jobs', job_input(erp), status=201)
    base = path('asset', asset['id'])
    for bad in (payload(b''), payload(b'bad'), payload(PDF, '../bad.pdf'),
                payload(PDF, 'bad.exe'), {**payload(), 'content_base64': '%%%='},
                {**payload(), 'reason': ' '}, payload(PDF+b'x'*(5*1024*1024))):
        api('POST', base, bad, status=422)
    api('POST', base, payload(), actor='observer', status=403)
    item = api('POST', base, payload(), status=201)
    api('GET', path('job', job['id'])+f'/{item["id"]}', status=404)
    api('POST', path('job', job['id'])+f'/{item["id"]}/reverse',
        {'reason': '跨单据'}, status=404)
    for number in range(1, 10):
        api('POST', base, payload(PDF+str(number).encode()), status=201)
    api('POST', base, payload(PDF+b'overflow'), status=409)


def test_terminal_records_are_read_only(erp):
    api, asset = erp[1], erp[4]
    job = api('POST', 'equipment/jobs', job_input(erp), status=201)
    base = path('job', job['id'])
    item = api('POST', base, payload(), status=201)
    job = action(api, job, 'cancel')
    assert api('GET', base)['can_modify'] is False
    api('POST', base, payload(PDF+b'later'), status=409)
    api('POST', base+f'/{item["id"]}/reverse', {'reason': '终态'}, status=409)
    assert api('GET', base)['items'][0]['id'] == item['id']
    updated = api('PUT', f'equipment/assets/{asset["id"]}',
        {'code':asset['code'], 'name':asset['name'], 'serial_number':asset['serial_number'],
         'location':asset['location'], 'status':'retired', 'reason':'设备报废', 'version':asset['version']})
    asset_base = path('asset', updated['id'])
    assert api('GET', asset_base)['can_modify'] is False
    api('POST', asset_base, payload(), status=409)


def test_v76_upgrade_retains_existing_records(erp):
    api, asset = erp[1], erp[4]
    with connection() as db:
        db.execute('DROP TABLE equipment_attachment_reversals')
        db.execute('DROP TABLE equipment_attachments')
        db.execute("DELETE FROM role_permissions WHERE permission_code='equipment.attachment'")
        db.execute("DELETE FROM permissions WHERE code='equipment.attachment'")
        db.execute('PRAGMA user_version=76')
    migrate()
    migrate()
    with connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 82
        assert db.execute('SELECT name FROM equipment_assets WHERE id=?',
            (asset['id'],)).fetchone()[0] == asset['name']
        assert db.execute("SELECT COUNT(*) FROM role_permissions WHERE permission_code='equipment.attachment'").fetchone()[0] == 3
    assert len(Base.metadata.tables) == 180
    assert api('POST', path('asset', asset['id']), payload(), status=201)['id'] > 0
