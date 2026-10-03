import assert from 'node:assert/strict'
import { test } from 'node:test'

import { callBackend } from '../src/main/backend.ts'
import { materialReturnLotBody } from '../src/shared/material-return-lot-api.ts'
import { physicalLotKindLabel } from '../src/shared/physical-lot-api.ts'

const lines = [{return_line_id: 7, lots: [
  {lot_id: 11, quantity: '0.250', supplier_lot: null, manufactured_on: null, expires_on: null,
    injected: 'ignored'},
  {lot_id: null, quantity: '0.750', supplier_lot: 'RETURNED', manufactured_on: '2026-09-01',
    expires_on: '2027-09-01'}]}]

test('生产退料 IPC 限定回仓批次字段并核对服务端凭据', async t => {
  const calls = []
  let oldServer = false
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({path: url.pathname, body: options.body})
    if (url.pathname.endsWith('/login')) return Response.json({token: 'test-token', user: {id: 1}})
    if (url.pathname.endsWith('/available-lots')) return Response.json({
      return_id: 3, material_issue_id: 2, warehouse_id: 1,
      lines: [{return_line_id: 7, material_issue_line_id: 5, material_id: 9,
        quantity: '1.000', lots: [{lot_id: 11, code: 'LOT-11', source_kind: 'receipt',
          quantity: '1.000', supplier_lot: null, manufactured_on: null, expires_on: null}]}]})
    if (options.body && !oldServer) return Response.json({id: 3, status: 'posted', lines: [{id: 7,
      physical_lots: [{id: 11, quantity: '0.250'},
        {id: 12, quantity: '0.750', source_kind: 'material_return'}]}]})
    return Response.json({id: 3, status: 'posted', lines: [{id: 7, physical_lots: []}]})
  })
  await callBackend('login', {})
  const options = await callBackend('availableMaterialReturnLots', {returnId: 3})
  assert.equal(options.lines[0].lots[0].quantity, '1.000')
  await callBackend('postMaterialReturn', {returnId: 3, lines, other: 'ignored'})
  assert.equal(calls.at(-1).path, '/api/v1/material-returns/3/post')
  assert.deepEqual(JSON.parse(calls.at(-1).body), {lines: [{return_line_id: 7, lots: [
    {lot_id: 11, quantity: '0.250', supplier_lot: null, manufactured_on: null, expires_on: null},
    {lot_id: null, quantity: '0.750', supplier_lot: 'RETURNED',
      manufactured_on: '2026-09-01', expires_on: '2027-09-01'}]}]})
  await callBackend('postMaterialReturn', {returnId: 3})
  assert.equal(calls.at(-1).body, undefined)
  oldServer = true
  await assert.rejects(callBackend('postMaterialReturn', {returnId: 3, lines}), /服务端未固定/)
  const before = calls.length
  for (const invalid of [
    [{...lines[0], return_line_id: 0}],
    [lines[0], lines[0]],
    [{...lines[0], lots: [{...lines[0].lots[0], quantity: '0'}]}],
    [{...lines[0], lots: [{...lines[0].lots[0], supplier_lot: '伪造'}]}],
    [{...lines[0], lots: [lines[0].lots[0], lines[0].lots[0]]}],
  ]) await assert.rejects(callBackend('postMaterialReturn', {returnId: 3, lines: invalid}))
  await assert.rejects(callBackend('postMaterialReturn', {returnId: '../users', lines}))
  assert.equal(calls.length, before)
  assert.equal(materialReturnLotBody({lines}).lines[0].lots[0].injected, undefined)
  assert.equal(physicalLotKindLabel('material_return'), '退料新批次')
})

test('生产退料冲销 IPC 限定编号和原因', async t => {
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({path: url.pathname, body: options.body})
    if (url.pathname.endsWith('/login')) return Response.json({token: 'test-token', user: {id: 1}})
    return Response.json({id: 3, status: 'reversed'})
  })
  await callBackend('login', {})
  await callBackend('reverseMaterialReturn', {returnId: 3, reason: '  登记错误  '})
  assert.equal(calls.at(-1).path, '/api/v1/material-returns/3/reverse')
  assert.deepEqual(JSON.parse(calls.at(-1).body), {reason: '登记错误'})
  const before = calls.length
  await assert.rejects(callBackend('reverseMaterialReturn', {returnId: '../users', reason: '原因'}))
  await assert.rejects(callBackend('reverseMaterialReturn', {returnId: 3, reason: ' '}))
  await assert.rejects(callBackend('reverseMaterialReturn', {returnId: 3, reason: '错误\n原因'}))
  assert.equal(calls.length, before)
})
