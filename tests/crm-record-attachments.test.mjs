import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { test } from 'node:test'
import { callBackend, fetchCrmRecordAttachment } from '../src/main/backend.ts'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createCrmActions } from '../src/renderer/src/store/modules/crm-actions.ts'
import { validateCrmRecordAttachmentResult } from '../src/shared/crm-record-attachment-validation.ts'

const pdf = Buffer.from('%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n')
const base64 = pdf.toString('base64')
const item = { id: 9, entity_kind: 'contact', entity_id: 7, file_name: '来函.pdf', media_type: 'application/pdf',
  byte_count: pdf.length, sha256: createHash('sha256').update(pdf).digest('hex'),
  reason: '依据', created_by: 1, created_by_name: 'admin', created_at: '2026-10-04 12:00:00', reversal: null }

test('客户关系附件固定路径只转发白名单字段并拒绝伪造类型和文件', async t => {
  const old = process.env.NEXORA_API_URL
  t.after(() => { if (old === undefined) delete process.env.NEXORA_API_URL; else process.env.NEXORA_API_URL = old })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8123'
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ path: url.pathname, method: options.method, body: options.body })
    if (url.pathname.endsWith('/login')) return Response.json({ token: 'attachment-test', user: { id: 1 } })
    if (url.pathname.endsWith('/reverse')) return Response.json({ ...item, reversal: {
      id: 1, reason: '误传', created_by: 1, created_by_name: 'admin', created_at: '2026-10-04 12:01:00' } })
    if (options.method === 'GET') return Response.json({ entity_kind: 'contact', entity_id: 7, can_modify: true, items: [] })
    return Response.json(item)
  })
  await callBackend('login', {})
  await callBackend('crmRecordAttachments', { kind: 'contact', id: 7, path: '/etc/passwd' })
  assert.deepEqual(calls.at(-1), { path: '/api/v1/crm/records/contact/7/attachments', method: 'GET', body: undefined })
  await callBackend('addCrmRecordAttachment', { kind: 'contact', id: 7,
    file_name: '来函.pdf', content_base64: base64, reason: '依据', path: '/etc/passwd' })
  assert.deepEqual(calls.at(-1), { path: '/api/v1/crm/records/contact/7/attachments', method: 'POST',
    body: JSON.stringify({ file_name: '来函.pdf', content_base64: base64, reason: '依据' }) })
  await callBackend('reverseCrmRecordAttachment', { kind: 'contact', id: 7, attachmentId: 9, reason: '误传', extra: true })
  assert.deepEqual(calls.at(-1), { path: '/api/v1/crm/records/contact/7/attachments/9/reverse', method: 'POST',
    body: JSON.stringify({ reason: '误传' }) })
  const before = calls.length
  for (const input of [
    { kind: 'quote', id: 7, file_name: '来函.pdf', content_base64: base64, reason: '依据' },
    { kind: '../users', id: 7, file_name: '来函.pdf', content_base64: base64, reason: '依据' },
    { kind: 'contact', id: '../users', file_name: '来函.pdf', content_base64: base64, reason: '依据' },
    { kind: 'contact', id: 7, file_name: '../来函.pdf', content_base64: base64, reason: '依据' },
    { kind: 'contact', id: 7, file_name: '来函.exe', content_base64: base64, reason: '依据' },
    { kind: 'contact', id: 7, file_name: '来函.pdf', content_base64: 'invalid%', reason: '依据' }
  ]) await assert.rejects(callBackend('addCrmRecordAttachment', input))
  assert.equal(calls.length, before)
})

test('客户关系附件响应拒绝跨类型、跨记录和虚假撤销', () => {
  assert.throws(() => validateCrmRecordAttachmentResult('crmRecordAttachments',
    { entity_kind: 'activity', entity_id: 7, can_modify: true, items: [item] }, 'contact', 7), /响应格式无效/)
  assert.throws(() => validateCrmRecordAttachmentResult('addCrmRecordAttachment',
    { ...item, entity_id: 8 }, 'contact', 7), /响应格式无效/)
  assert.throws(() => validateCrmRecordAttachmentResult('addCrmRecordAttachment',
    { ...item, sha256: 'broken' }, 'contact', 7), /响应格式无效/)
  assert.throws(() => validateCrmRecordAttachmentResult('reverseCrmRecordAttachment', item, 'contact', 7), /撤销响应格式无效/)
})

test('客户关系附件读取验证摘要和文件类型，并阻止旧会话保存', async t => {
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
  const file = await fetchCrmRecordAttachment('contact', 7, 9)
  assert.equal(file.kind, 'contact')
  assert.equal(file.recordId, 7)
  assert.equal(file.attachmentId, 9)
  assert.deepEqual(file.bytes, pdf)
  assert.equal(file.isCurrent(), true)
  corrupt = true
  await assert.rejects(fetchCrmRecordAttachment('contact', 7, 9), /校验失败/)
  await callBackend('login', {})
  assert.equal(file.isCurrent(), false)
  await assert.rejects(fetchCrmRecordAttachment('../users', 7, 9), /记录类型无效/)
})

test('切换账号后不返回旧账号的客户关系附件结果', async t => {
  const old = globalThis.window
  t.after(() => { globalThis.window = old })
  const state = createAppState()
  state.user.value = { id: 1, permissions: ['crm.view', 'crm.attachment'] }
  let resolveList
  globalThis.window = { nexora: {
    callApi: (action) => action === 'crmRecordAttachments' ? new Promise(resolve => { resolveList = resolve }) : Promise.resolve({}),
    uploadCrmRecordAttachment: async () => ({ id: 5 }),
    saveCrmRecordAttachment: async () => 'saved.pdf'
  } }
  const actions = createCrmActions(state, async fn => { await fn() })
  const pending = actions.loadCrmRecordAttachments('contact', 7)
  state.user.value = { id: 2, permissions: ['crm.view', 'crm.attachment'] }
  resolveList({ entity_kind: 'contact', entity_id: 7, can_modify: true, items: [{ id: 5 }] })
  await assert.rejects(pending, /会话或权限已变化/)
  assert.deepEqual(await actions.uploadCrmRecordAttachment('contact', 7, '原件'), { id: 5 })
  assert.equal(await actions.saveCrmRecordAttachment('contact', 7, 5), 'saved.pdf')
})
