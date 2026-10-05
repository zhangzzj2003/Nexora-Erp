import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { test } from 'node:test'
import { callBackend, fetchSalesContractAttachment } from '../src/main/backend.ts'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createSalesActions } from '../src/renderer/src/store/modules/sales-actions.ts'
import { validateSalesContractAttachmentResult } from '../src/shared/sales-contract-attachment-validation.ts'

const pdf = Buffer.from('%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n')
const base64 = pdf.toString('base64')
const item = { id: 9, revision_id: 6, file_name: '合同.pdf', media_type: 'application/pdf',
  byte_count: pdf.length, sha256: createHash('sha256').update(pdf).digest('hex'),
  reason: '客户签收', created_by: 1, created_by_name: 'admin', created_at: '2026-10-06 12:00:00', reversal: null }

test('合同附件 IPC 固定订单与版本路径且只转发白名单字段', async t => {
  const old = process.env.NEXORA_API_URL
  t.after(() => { if (old === undefined) delete process.env.NEXORA_API_URL; else process.env.NEXORA_API_URL = old })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8123'
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ path: url.pathname, method: options.method, body: options.body })
    if (url.pathname.endsWith('/login')) return Response.json({ token: 'contract-file-test', user: { id: 1 } })
    if (url.pathname.endsWith('/reverse')) return Response.json({ ...item, reversal: {
      id: 1, reason: '误传', created_by: 1, created_by_name: 'admin', created_at: '2026-10-06 12:01:00' } })
    if (options.method === 'GET') return Response.json({ order_id: 7, revision_id: 6, can_modify: true, items: [] })
    return Response.json(item)
  })
  await callBackend('login', {})
  await callBackend('salesContractAttachments', { orderId: 7, revisionId: 6, path: '/etc/passwd' })
  assert.deepEqual(calls.at(-1), { path: '/api/v1/sales-orders/7/contract/revisions/6/attachments',
    method: 'GET', body: undefined })
  await callBackend('addSalesContractAttachment', { orderId: 7, revisionId: 6,
    file_name: '合同.pdf', content_base64: base64, reason: '客户签收', extra: true })
  assert.deepEqual(calls.at(-1), { path: '/api/v1/sales-orders/7/contract/revisions/6/attachments',
    method: 'POST', body: JSON.stringify({ file_name: '合同.pdf', content_base64: base64, reason: '客户签收' }) })
  await callBackend('reverseSalesContractAttachment', { orderId: 7, revisionId: 6,
    attachmentId: 9, reason: '误传', extra: true })
  assert.deepEqual(calls.at(-1), { path: '/api/v1/sales-orders/7/contract/revisions/6/attachments/9/reverse',
    method: 'POST', body: JSON.stringify({ reason: '误传' }) })
  const before = calls.length
  for (const input of [
    { orderId: '../users', revisionId: 6, file_name: '合同.pdf', content_base64: base64, reason: '依据' },
    { orderId: 7, revisionId: '../users', file_name: '合同.pdf', content_base64: base64, reason: '依据' },
    { orderId: 7, revisionId: 6, file_name: '../bad.pdf', content_base64: base64, reason: '依据' },
    { orderId: 7, revisionId: 6, file_name: 'bad.exe', content_base64: base64, reason: '依据' },
    { orderId: 7, revisionId: 6, file_name: '合同.pdf', content_base64: 'invalid%', reason: '依据' }
  ]) await assert.rejects(callBackend('addSalesContractAttachment', input))
  assert.equal(calls.length, before)
})

test('合同附件响应拒绝跨订单、跨版本和虚假撤销', () => {
  assert.throws(() => validateSalesContractAttachmentResult('salesContractAttachments',
    { order_id: 8, revision_id: 6, can_modify: true, items: [item] }, 7, 6), /响应格式无效/)
  assert.throws(() => validateSalesContractAttachmentResult('salesContractAttachments',
    { order_id: 7, revision_id: 8, can_modify: true, items: [item] }, 7, 6), /响应格式无效/)
  assert.throws(() => validateSalesContractAttachmentResult('addSalesContractAttachment',
    { ...item, revision_id: 8 }, 7, 6), /响应格式无效/)
  assert.throws(() => validateSalesContractAttachmentResult('reverseSalesContractAttachment',
    item, 7, 6), /撤销响应格式无效/)
})

test('合同附件导出核对摘要、格式与当前会话', async t => {
  const old = process.env.NEXORA_API_URL
  t.after(() => { if (old === undefined) delete process.env.NEXORA_API_URL; else process.env.NEXORA_API_URL = old })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8123'
  let corrupt = false
  t.mock.method(globalThis, 'fetch', async (url) => {
    if (url.pathname.endsWith('/login')) return Response.json({ token: corrupt ? 'new-user' : 'old-user', user: { id: 1 } })
    assert.equal(url.pathname, '/api/v1/sales-orders/7/contract/revisions/6/attachments/9')
    return new Response(pdf, { headers: { 'content-type': 'application/octet-stream',
      'x-nexora-sha256': corrupt ? '0'.repeat(64) : item.sha256, 'x-nexora-file-extension': '.pdf' } })
  })
  await callBackend('login', {})
  const file = await fetchSalesContractAttachment(7, 6, 9)
  assert.equal(file.orderId, 7)
  assert.equal(file.revisionId, 6)
  assert.deepEqual(file.bytes, pdf)
  assert.equal(file.isCurrent(), true)
  corrupt = true
  await assert.rejects(fetchSalesContractAttachment(7, 6, 9), /校验失败/)
  await callBackend('login', {})
  assert.equal(file.isCurrent(), false)
  await assert.rejects(fetchSalesContractAttachment(7, '../users', 9), /记录编号无效/)
})

test('账号切换后丢弃旧合同附件列表与上传结果', async t => {
  const old = globalThis.window
  t.after(() => { globalThis.window = old })
  const state = createAppState()
  state.user.value = { id: 1, permissions: ['sales.view', 'sales_order.confirm'] }
  let resolveList
  globalThis.window = { nexora: {
    callApi: (action) => action === 'salesContractAttachments'
      ? new Promise(resolve => { resolveList = resolve }) : Promise.resolve(item),
    uploadSalesContractAttachment: async () => item,
    saveSalesContractAttachment: async () => 'saved.pdf'
  } }
  const actions = createSalesActions(state, async fn => { await fn() })
  const pending = actions.loadSalesContractAttachments(7, 6)
  state.user.value = { id: 2, permissions: ['sales.view', 'sales_order.confirm'] }
  resolveList({ order_id: 7, revision_id: 6, can_modify: true, items: [item] })
  await assert.rejects(pending, /会话或权限已变化/)
  assert.deepEqual(await actions.uploadSalesContractAttachment(7, 6, '依据'), item)
  assert.equal(await actions.saveSalesContractAttachment(7, 6, 9), 'saved.pdf')
})

test('同一账号重新登录也不接受退出前的附件响应', async t => {
  const old = globalThis.window
  t.after(() => { globalThis.window = old })
  const state = createAppState()
  const actor = { id: 1, permissions: ['sales.view', 'sales_order.confirm'] }
  state.user.value = actor
  let resolveList
  globalThis.window = { nexora: { callApi: () => new Promise(resolve => { resolveList = resolve }) } }
  const actions = createSalesActions(state, async fn => { await fn() })
  const pending = actions.loadSalesContractAttachments(7, 6)
  state.user.value = null
  state.user.value = actor
  resolveList({ order_id: 7, revision_id: 6, can_modify: true, items: [item] })
  await assert.rejects(pending, /会话或权限已变化/)
})
