import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { validateCapture, captureSink } from '../scripts/site-preview/capture-sink.mjs'
import { captureFile, captureSvg } from '../scripts/site-preview/capture.mjs'

// 取景工具只能保存已约定的三张图，不能通过文件名改写其他仓库文件。
test('高清取景校验真实 PNG、尺寸、大小和文件白名单', () => {
  const png = readFileSync(new URL('../docs/site/screenshots/receipts@3x.png', import.meta.url))
  assert.equal(validateCapture('/__preview_capture/receipts@3x.png', png), 'receipts@3x.png')
  for (const path of ['/__preview_capture/../../README.md', '/__preview_capture/home.png', '/other/receipts@3x.png', '/__preview_capture/receipts@3x.png?x=1']) assert.throws(() => validateCapture(path, png), /不允许/)
  assert.throws(() => validateCapture('/__preview_capture/receipts@3x.png', Buffer.alloc(4)), /高清 PNG/)
  const wrongSize = Buffer.from(png); wrongSize.writeUInt32BE(1800, 16)
  assert.throws(() => validateCapture('/__preview_capture/receipts@3x.png', wrongSize), /高清 PNG/)
  assert.throws(() => validateCapture('/__preview_capture/receipts@3x.png', Buffer.alloc(20 * 1024 * 1024 + 1)), /高清 PNG/)
  assert.equal(captureFile('/workspace/receipts'), 'receipts@3x.png')
  assert.equal(captureFile('/workspace/inventory-ledger'), 'inventory@3x.png')
  assert.equal(captureFile('/workspace/financial-sources'), 'sources@3x.png')
  assert.equal(captureFile('/workspace/home'), null)
  // 防止退回先栅格化 1800 像素再放大的模糊图片。
  const svg = captureSvg('<div>实际明细</div>')
  assert.match(svg, /width="5400" height="3600" viewBox="0 0 1800 1200"/)
  assert.match(svg, /<foreignObject width="1800" height="1200"><div>实际明细/)
})

test('取景写图入口拒绝跨源和非 POST 请求，普通页面仍交给预览服务器', async () => {
  const sink = captureSink('/unused'), response = { end(body) { this.body = body } }
  for (const request of [{ method: 'GET', headers: { origin: 'http://127.0.0.1:8766' } }, { method: 'POST', headers: { origin: 'https://example.org' } }]) {
    await sink({ ...request, url: '/__preview_capture/receipts@3x.png' }, response, () => assert.fail('禁止请求不能继续'))
    assert.equal(response.statusCode, 400); assert.match(response.body, /本地预览/)
  }
  let next = false
  await sink({ url: '/scripts/site-preview/index.html' }, response, () => { next = true })
  assert.equal(next, true)
})
