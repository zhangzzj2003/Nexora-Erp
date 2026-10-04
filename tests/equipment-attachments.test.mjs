import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { test } from 'node:test'
import { callBackend, fetchEquipmentAttachment } from '../src/main/backend.ts'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createEquipmentActions } from '../src/renderer/src/store/modules/equipment-actions.ts'
import { validateEquipmentAttachmentResult } from '../src/shared/equipment-attachment-validation.ts'

const pdf = Buffer.from('%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n')
const base64 = pdf.toString('base64')
const item = { id: 9, entity_kind: 'asset', entity_id: 7, file_name: '现场.pdf', media_type: 'application/pdf',
  byte_count: pdf.length, sha256: createHash('sha256').update(pdf).digest('hex'),
  reason: '依据', created_by: 1, created_by_name: 'admin', created_at: '2026-10-04 12:00:00', reversal: null }

test('设备维护附件固定路径只转发白名单字段并拒绝伪造类型和文件', async t => {
  const old = process.env.NEXORA_API_URL
  t.after(() => { if (old === undefined) delete process.env.NEXORA_API_URL; else process.env.NEXORA_API_URL = old })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8123'
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ path: url.pathname, method: options.method, body: options.body })
    if (url.pathname.endsWith('/login')) return Response.json({ token: 'attachment-test', user: { id: 1 } })
    if (url.pathname.endsWith('/reverse')) return Response.json({ ...item, reversal: {
      id: 1, reason: '误传', created_by: 1, created_by_name: 'admin', created_at: '2026-10-04 12:01:00' } })
    if (options.method === 'GET') return Response.json({ entity_kind: 'asset', entity_id: 7, can_modify: true, items: [] })
    return Response.json(item)
  })
  await callBackend('login', {})
  await callBackend('equipmentAttachments', { kind: 'asset', id: 7, path: '/etc/passwd' })
  assert.deepEqual(calls.at(-1), { path: '/api/v1/equipment/asset/7/attachments', method: 'GET', body: undefined })
  await callBackend('addEquipmentAttachment', { kind: 'asset', id: 7,
    file_name: '现场.pdf', content_base64: base64, reason: '依据', path: '/etc/passwd' })
  assert.deepEqual(calls.at(-1), { path: '/api/v1/equipment/asset/7/attachments', method: 'POST',
    body: JSON.stringify({ file_name: '现场.pdf', content_base64: base64, reason: '依据' }) })
  await callBackend('reverseEquipmentAttachment', { kind: 'asset', id: 7, attachmentId: 9, reason: '误传', extra: true })
  assert.deepEqual(calls.at(-1), { path: '/api/v1/equipment/asset/7/attachments/9/reverse', method: 'POST',
    body: JSON.stringify({ reason: '误传' }) })
  const before = calls.length
  for (const input of [
    { kind: 'plan', id: 7, file_name: '现场.pdf', content_base64: base64, reason: '依据' },
    { kind: '../users', id: 7, file_name: '现场.pdf', content_base64: base64, reason: '依据' },
    { kind: 'asset', id: '../users', file_name: '现场.pdf', content_base64: base64, reason: '依据' },
    { kind: 'asset', id: 7, file_name: '../现场.pdf', content_base64: base64, reason: '依据' },
    { kind: 'asset', id: 7, file_name: '来函.exe', content_base64: base64, reason: '依据' },
    { kind: 'asset', id: 7, file_name: '现场.pdf', content_base64: 'invalid%', reason: '依据' }
  ]) await assert.rejects(callBackend('addEquipmentAttachment', input))
  assert.equal(calls.length, before)
})

test('设备维护附件响应拒绝跨类型、跨记录和虚假撤销', () => {
  assert.throws(() => validateEquipmentAttachmentResult('equipmentAttachments',
    { entity_kind: 'job', entity_id: 7, can_modify: true, items: [item] }, 'asset', 7), /响应格式无效/)
  assert.throws(() => validateEquipmentAttachmentResult('addEquipmentAttachment',
    { ...item, entity_id: 8 }, 'asset', 7), /响应格式无效/)
  assert.throws(() => validateEquipmentAttachmentResult('addEquipmentAttachment',
    { ...item, sha256: 'broken' }, 'asset', 7), /响应格式无效/)
  assert.throws(() => validateEquipmentAttachmentResult('reverseEquipmentAttachment', item, 'asset', 7), /撤销响应格式无效/)
})

test('设备维护附件读取验证摘要和文件类型，并阻止旧会话保存', async t => {
  const old = process.env.NEXORA_API_URL
  t.after(() => { if (old === undefined) delete process.env.NEXORA_API_URL; else process.env.NEXORA_API_URL = old })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8123'
  const digest = createHash('sha256').update(pdf).digest('hex')
  let corrupt = false
  t.mock.method(globalThis, 'fetch', async (url) => {
    if (url.pathname.endsWith('/login')) return Response.json({ token: corrupt ? 'new-user' : 'old-user', user: { id: 1 } })
    return new Response(pdf, { headers: { 'content-type': 'application/octet-stream',
      'x-nexora-sha256': corrupt ? '0'.repeat(64) : digest, 'x-nexora-file-extension': '.pdf' } })
  })
  await callBackend('login', {})
  const file = await fetchEquipmentAttachment('asset', 7, 9)
  assert.equal(file.kind, 'asset')
  assert.equal(file.recordId, 7)
  assert.equal(file.attachmentId, 9)
  assert.deepEqual(file.bytes, pdf)
  assert.equal(file.isCurrent(), true)
  corrupt = true
  await assert.rejects(fetchEquipmentAttachment('asset', 7, 9), /校验失败/)
  await callBackend('login', {})
  assert.equal(file.isCurrent(), false)
  await assert.rejects(fetchEquipmentAttachment('../users', 7, 9), /附件类型无效/)
})

test('切换账号后不返回旧账号的设备维护附件结果', async t => {
  const old = globalThis.window
  t.after(() => { globalThis.window = old })
  const state = createAppState()
  state.user.value = { id: 1, permissions: ['equipment.view', 'equipment.attachment'] }
  let resolveList
  globalThis.window = { nexora: {
    callApi: (action) => action === 'equipmentAttachments' ? new Promise(resolve => { resolveList = resolve }) : Promise.resolve({}),
    uploadEquipmentAttachment: async () => ({ id: 5 }),
    saveEquipmentAttachment: async () => 'saved.pdf'
  } }
  const actions = createEquipmentActions(state, async fn => { await fn() })
  const pending = actions.loadEquipmentAttachments('asset', 7)
  state.user.value = { id: 2, permissions: ['equipment.view', 'equipment.attachment'] }
  resolveList({ entity_kind: 'asset', entity_id: 7, can_modify: true, items: [{ id: 5 }] })
  await assert.rejects(pending, /会话或权限已变化/)
  assert.deepEqual(await actions.uploadEquipmentAttachment('asset', 7, '原件'), { id: 5 })
  assert.equal(await actions.saveEquipmentAttachment('asset', 7, 5), 'saved.pdf')
})
