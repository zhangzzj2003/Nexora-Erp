import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { test } from 'node:test'
import { callBackend, fetchJournalAttachment } from '../src/main/backend.ts'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createJournalActions } from '../src/renderer/src/store/modules/journal-actions.ts'
import { validateJournalAttachmentResult } from '../src/shared/journal-attachment-validation.ts'

const pdf = Buffer.from('%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n')
const base64 = pdf.toString('base64')
const item = { id: 9, journal_id: 7, file_name: '票据.pdf', media_type: 'application/pdf',
  byte_count: pdf.length, sha256: createHash('sha256').update(pdf).digest('hex'),
  reason: '依据', created_by: 1, created_by_name: 'admin', created_at: '2026-10-04 12:00:00', reversal: null }

test('附件固定 IPC 路径只转发白名单字段并拒绝非法文件', async t => {
  const old = process.env.NEXORA_API_URL
  t.after(() => { if (old === undefined) delete process.env.NEXORA_API_URL; else process.env.NEXORA_API_URL = old })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8123'
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ path: url.pathname, method: options.method, body: options.body })
    if (url.pathname.endsWith('/login')) return Response.json({ token: 'attachment-test', user: { id: 1 } })
    if (url.pathname.endsWith('/reverse')) return Response.json({ ...item, reversal: {
      id: 1, reason: '误传', created_by: 1, created_by_name: 'admin', created_at: '2026-10-04 12:01:00' } })
    if (options.method === 'GET') return Response.json({ journal_id: 7, can_modify: true, items: [] })
    return Response.json(item)
  })
  await callBackend('login', {})
  await callBackend('journalAttachments', { id: 7, path: '/etc/passwd' })
  assert.deepEqual(calls.at(-1), { path: '/api/v1/finance/journals/7/attachments', method: 'GET', body: undefined })
  await callBackend('addJournalAttachment', { id: 7, file_name: '票据.pdf', content_base64: base64,
    reason: '依据', path: '/etc/passwd', media_type: 'application/x-danger' })
  assert.deepEqual(calls.at(-1), { path: '/api/v1/finance/journals/7/attachments', method: 'POST',
    body: JSON.stringify({ file_name: '票据.pdf', content_base64: base64, reason: '依据' }) })
  await callBackend('reverseJournalAttachment', { journalId: 7, attachmentId: 9, reason: '误传', extra: true })
  assert.deepEqual(calls.at(-1), { path: '/api/v1/finance/journals/7/attachments/9/reverse', method: 'POST',
    body: JSON.stringify({ reason: '误传' }) })
  const before = calls.length
  for (const input of [
    { id: '../users', file_name: '票据.pdf', content_base64: base64, reason: '依据' },
    { id: 7, file_name: '../票据.pdf', content_base64: base64, reason: '依据' },
    { id: 7, file_name: '票据.exe', content_base64: base64, reason: '依据' },
    { id: 7, file_name: '票据.pdf', content_base64: 'invalid%', reason: '依据' },
    { id: 7, file_name: '票据.pdf', content_base64: base64, reason: ' ' }
  ]) await assert.rejects(callBackend('addJournalAttachment', input))
  await assert.rejects(callBackend('reverseJournalAttachment', { journalId: 7, attachmentId: '../users', reason: '误传' }))
  assert.equal(calls.length, before)
})

test('附件响应拒绝跨凭证、缺摘要和虚假撤销结果', () => {
  assert.throws(() => validateJournalAttachmentResult('journalAttachments',
    { journal_id: 8, can_modify: true, items: [item] }, 7), /响应格式无效/)
  assert.throws(() => validateJournalAttachmentResult('addJournalAttachment',
    { ...item, sha256: 'broken' }, 7), /响应格式无效/)
  assert.throws(() => validateJournalAttachmentResult('reverseJournalAttachment', item, 7), /撤销响应格式无效/)
})

test('附件导出核对类型与 SHA-256，且会话变化使旧文件失效', async t => {
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
  const file = await fetchJournalAttachment(7, 9)
  assert.equal(file.journalId, 7)
  assert.equal(file.attachmentId, 9)
  assert.equal(file.extension, '.pdf')
  assert.deepEqual(file.bytes, pdf)
  assert.equal(file.isCurrent(), true)
  corrupt = true
  await assert.rejects(fetchJournalAttachment(7, 9), /校验失败/)
  await callBackend('login', {})
  assert.equal(file.isCurrent(), false)
  await assert.rejects(fetchJournalAttachment('../users', 9), /记录编号无效/)
})

test('附件业务操作在账号切换后不返回旧账号的列表或上传结果', async t => {
  const old = globalThis.window
  t.after(() => { globalThis.window = old })
  const state = createAppState()
  state.user.value = { id: 1, permissions: ['journal.view', 'journal.attachment'] }
  let resolveList
  globalThis.window = { nexora: {
    callApi: (action) => action === 'journalAttachments' ? new Promise(resolve => { resolveList = resolve }) : Promise.resolve({}),
    uploadJournalAttachment: async () => ({ id: 5 }),
    saveJournalAttachment: async () => 'saved.pdf'
  } }
  const actions = createJournalActions(state, async fn => { await fn() })
  const pending = actions.loadJournalAttachments(7)
  state.user.value = { id: 2, permissions: ['journal.view'] }
  resolveList({ journal_id: 7, can_modify: true, items: [{ id: 5 }] })
  await assert.rejects(pending, /会话或权限已变化/)
  assert.deepEqual(await actions.uploadJournalAttachment(7, '原件'), { id: 5 })
  assert.equal(await actions.saveJournalAttachment(7, 5), 'saved.pdf')
})
