import { materialDraft, materialInput } from '../src/renderer/src/views/workspace/catalog/material-form.ts'
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { callBackend, getBackendHealth, retainedSessionToken } from '../src/main/backend.ts'

test('采购列表和确认响应在主进程拒绝残缺审批状态', async t => {
  // 使用真实受限请求入口，防止只校验审批弹窗而遗漏业务列表和执行返回值。
  const originalUrl = process.env.NEXORA_API_URL
  t.after(() => {
    if (originalUrl === undefined) delete process.env.NEXORA_API_URL
    else process.env.NEXORA_API_URL = originalUrl
  })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8123'
  let output
  t.mock.method(globalThis, 'fetch', async url => url.pathname.endsWith('/login')
    ? Response.json({ token: 'test-token', user: { id: 1 } }) : Response.json(output))
  await callBackend('login', {})
  const state = { version: 2, status: 'approved', generation: 1, current_step: 1,
    steps: [{ name: '批准', role: null }], policy_version: 1,
    submitted_by: 1, submitted_at: '2026-10-07 12:00:00', executed_by: null, executed_at: null }
  for (const [action, input, list] of [
    ['purchaseOrders', undefined, true], ['goodsReceipts', undefined, true], ['receipts', undefined, true],
    ['confirmPurchaseOrder', { orderId: 7 }, false],
    ['confirmGoodsReceipt', { goodsReceiptId: 7 }, false], ['postReceipt', { receiptId: 7 }, false]
  ]) {
    const row = { id: 7, approval: state }
    output = list ? [row] : row
    assert.deepEqual(await callBackend(action, input), output)
    const malformed = { id: 7, approval: { status: 'approved' } }
    output = list ? [malformed] : malformed
    await assert.rejects(callBackend(action, input), /审批状态无效/)
  }
})

test('成本结算与冲销仅访问固定接口，拒绝非法路径编号', async t => {
  const originalUrl = process.env.NEXORA_API_URL
  t.after(() => {
    if (originalUrl === undefined) delete process.env.NEXORA_API_URL
    else process.env.NEXORA_API_URL = originalUrl
  })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8123'
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ path: url.pathname, method: options.method, body: options.body })
    return Response.json({ token: 'test-token', user: { id: 1 } })
  })
  await callBackend('login', {})
  await callBackend('productionCostSettlements', undefined)
  assert.equal(calls.at(-1).path, '/api/v1/production-costs/settlements')
  await callBackend('settleProductionCost', { work_order_id: 7, reference: 'COST-7', note: '' })
  assert.deepEqual(JSON.parse(calls.at(-1).body), { work_order_id: 7, reference: 'COST-7', note: '' })
  await callBackend('reverseProductionSettlement', { settlementId: 8, reason: '重算', extra: '不会转发' })
  assert.equal(calls.at(-1).path, '/api/v1/production-costs/settlements/8/reverse')
  assert.deepEqual(JSON.parse(calls.at(-1).body), { reason: '重算' })
  await assert.rejects(callBackend('reverseProductionSettlement', { settlementId: '../users', reason: '无效' }), /记录编号无效/)
})

test('订单间核销固定后端路径并校验撤销编号', async t => {
  const originalUrl = process.env.NEXORA_API_URL
  t.after(() => {
    if (originalUrl === undefined) delete process.env.NEXORA_API_URL
    else process.env.NEXORA_API_URL = originalUrl
  })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8123'
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ path: url.pathname, method: options.method, body: options.body })
    return Response.json({ token: 'test-token', user: { id: 1 } })
  })
  await callBackend('login', {})
  await callBackend('orderSettlements', undefined)
  assert.equal(calls.at(-1).path, '/api/v1/finance/order-settlements')
  const draft = { kind: 'receivable', from_order_id: 1, to_order_id: 2, amount: '6.00',
    reference: 'OFFSET-1', reason: '同一客户抵扣' }
  await callBackend('createOrderSettlement', draft)
  assert.deepEqual(JSON.parse(calls.at(-1).body), draft)
  await callBackend('reverseOrderSettlement', { transferId: 4, reason: '更正', extra: '不应转发' })
  assert.equal(calls.at(-1).path, '/api/v1/finance/order-settlements/4/reverse')
  assert.deepEqual(JSON.parse(calls.at(-1).body), { reason: '更正' })
  await assert.rejects(callBackend('reverseOrderSettlement', { transferId: '../users', reason: '无效' }), /记录编号无效/)
})

test('刷新同一已信任实例时保留会话，切换实例或证书时必须清除', () => {
  const current = { host: '192.168.3.5', port: 8000, instanceId: 'server-a', certificate: 'trusted-cert-a' }
  assert.equal(retainedSessionToken('private-token', current, { ...current }), 'private-token')
  // 同一实例换局域网地址时，服务端身份仍由实例编号和证书共同确定。
  assert.equal(retainedSessionToken('private-token', current, { ...current, host: '192.168.3.8' }), 'private-token')
  assert.equal(retainedSessionToken('private-token', current, { ...current, instanceId: 'server-b' }), null)
  assert.equal(retainedSessionToken('private-token', current, { ...current, certificate: 'changed-cert' }), null)
  assert.equal(retainedSessionToken('private-token', current, null), null)
  assert.equal(retainedSessionToken('private-token', null, current), null)
  assert.equal(retainedSessionToken(null, current, current), null)
})

test('后端连接契约与失败处理', async (t) => {
  const originalUrl = process.env.NEXORA_API_URL
  t.after(() => {
    if (originalUrl === undefined) delete process.env.NEXORA_API_URL
    else process.env.NEXORA_API_URL = originalUrl
  })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8123'
  const fetchMock = t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url.href, 'http://127.0.0.1:8123/api/v1/health')
    assert.equal(options.redirect, 'error')
    assert.ok(options.signal instanceof AbortSignal)
    return Response.json({ status: 'ok', service: 'nexora-api', version: '0.1.0' })
  })
  assert.deepEqual(await getBackendHealth(), { connected: true, version: '0.1.0' })
  for (const data of [null, {}, { status: 'ok', service: 'other', version: '1' }]) {
    fetchMock.mock.mockImplementation(async () => Response.json(data))
    assert.equal((await getBackendHealth()).connected, false)
  }
  fetchMock.mock.mockImplementation(async () => new Response('unavailable', { status: 503 }))
  assert.match((await getBackendHealth()).message, /503/)
  fetchMock.mock.mockImplementation(async () => new Response('invalid json'))
  assert.equal((await getBackendHealth()).connected, false)
  fetchMock.mock.mockImplementation(async () => { throw new Error('connection refused') })
  assert.equal((await getBackendHealth()).connected, false)
  process.env.NEXORA_API_URL = 'file:///tmp/test'
  assert.match((await getBackendHealth()).message, /配置无效/)
})

test('服务端缺少当前功能时显示可处理的中文提示', async (t) => {
  const originalUrl = process.env.NEXORA_API_URL
  t.after(() => {
    if (originalUrl === undefined) delete process.env.NEXORA_API_URL
    else process.env.NEXORA_API_URL = originalUrl
  })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8123'
  t.mock.method(globalThis, 'fetch', async (url) => {
    if (url.pathname.endsWith('/login')) {
      return Response.json({ token: 'test-token', user: { id: 1 } })
    }
    assert.equal(url.pathname, '/api/v1/inventory-ledger/query')
    return Response.json({ detail: 'Not Found' }, { status: 404 })
  })
  await callBackend('login', {})
  // 保留状态码和版本排查建议，避免直接把英文框架提示展示给用户。
  await assert.rejects(callBackend('inventoryLedger', {
    warehouse_id: null, material_id: null, from_date: null, to_date: null, source_type: null
  }), /服务端未找到此功能（HTTP 404）。请确认桌面端与服务端版本一致。/)
})

test('桌面业务接口只转发固定操作且令牌留在主进程', async (t) => {
  const originalUrl = process.env.NEXORA_API_URL
  t.after(() => {
    if (originalUrl === undefined) delete process.env.NEXORA_API_URL
    else process.env.NEXORA_API_URL = originalUrl
  })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8123'
  const calls = []
  const fetchMock = t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ path: url.pathname, search: url.search, method: options.method,
      authorization: options.headers.Authorization, body: options.body })
    if (url.pathname.endsWith('/login')) {
      return Response.json({ token: 'private-session-token', user: { id: 1, username: 'admin', roles: ['admin'], permissions: [] } })
    }
    if (url.pathname.endsWith('/logout')) return new Response(null, { status: 204 })
    return Response.json({ id: 1, username: 'admin', roles: ['admin'], permissions: [] })
  })
  const user = await callBackend('login', { username: 'admin', password: 'secure-pass-123' })
  assert.equal(user.username, 'admin')
  assert.equal(JSON.stringify(user).includes('private-session-token'), false)
  await callBackend('me', undefined)
  assert.equal(calls[1].authorization, 'Bearer private-session-token')
  await callBackend('postReceipt', { receiptId: 3 })
  assert.equal(calls[2].path, '/api/v1/receipts/3/post')
  await callBackend('setUserStatus', { userId: 2, is_active: false })
  assert.equal(calls[3].path, '/api/v1/users/2/status')
  await callBackend('updateRole', { code: 'stock_clerk', label: '库存员', permissions: ['inventory.view'] })
  assert.equal(calls[4].path, '/api/v1/roles/stock_clerk')
  // 新增仓库与调拨操作仍经过固定白名单，仓库筛选编号不能拼接任意路径。
  await callBackend('warehouses', undefined)
  assert.equal(calls[5].path, '/api/v1/warehouses')
  await callBackend('postTransfer', { transferId: 6 })
  assert.equal(calls[6].path, '/api/v1/transfers/6/post')
  await callBackend('stock', { warehouseId: 2 })
  assert.equal(calls[7].path, '/api/v1/stock')
  assert.equal(calls[7].search, '?warehouse_id=2')
  await assert.rejects(callBackend('stock', { warehouseId: '../users' }), /记录编号无效/)
  await assert.rejects(callBackend('postTransfer', { transferId: '../users' }), /记录编号无效/)
  // 采购订单确认也只能使用经校验的单据编号。
  await callBackend('confirmPurchaseOrder', { orderId: 9 })
  assert.equal(calls[8].path, '/api/v1/purchase-orders/9/confirm')
  await assert.rejects(callBackend('cancelPurchaseOrder', { orderId: '../users' }), /记录编号无效/)
  // 盘点确认与取消均使用受限的单据编号，不允许页面提供任意接口路径。
  await callBackend('postStocktake', { stocktakeId: 4 })
  assert.equal(calls[9].path, '/api/v1/stocktakes/4/post')
  await assert.rejects(callBackend('cancelStocktake', { stocktakeId: '../users' }), /记录编号无效/)
  // 销售出库只接收固定操作，单据编号由主进程校验后拼接。
  await callBackend('postShipment', { shipmentId: 5 })
  assert.equal(calls[10].path, '/api/v1/shipments/5/post')
  // 退货确认与取消都由主进程限定目标路径和编号。
  await callBackend('salesReturns', undefined)
  assert.equal(calls[11].path, '/api/v1/sales-returns')
  await callBackend('postSalesReturn', { returnId: 7 })
  assert.equal(calls[12].path, '/api/v1/sales-returns/7/post')
  await assert.rejects(callBackend('cancelSalesReturn', { returnId: '../users' }), /记录编号无效/)
  // 采购退货也必须固定接口路径，并拒绝伪造的单据编号。
  await callBackend('purchaseReturns', undefined)
  assert.equal(calls[13].path, '/api/v1/purchase-returns')
  await callBackend('postPurchaseReturn', { returnId: 8 })
  assert.equal(calls[14].path, '/api/v1/purchase-returns/8/post')
  await assert.rejects(callBackend('cancelPurchaseReturn', { returnId: '../users' }), /记录编号无效/)
  // 财务只读查询同样通过主进程的固定路径，不能由页面拼装任意后端地址。
  await callBackend('receivablesPayables', undefined)
  assert.equal(calls[15].path, '/api/v1/finance/receivables-payables')
  await callBackend('financeOverview', undefined)
  assert.equal(calls[16].path, '/api/v1/finance/overview')
  // 收付款与冲销只能调用固定接口，冲销编号在进入路径前校验。
  await callBackend('financeAccounts', undefined)
  assert.equal(calls[17].path, '/api/v1/finance/accounts')
  await callBackend('paymentRecords', undefined)
  assert.equal(calls[18].path, '/api/v1/finance/payment-records')
  await callBackend('reversePaymentRecord', { paymentId: 11, reason: '误录' })
  assert.equal(calls[19].path, '/api/v1/finance/payment-records/11/reverse')
  await assert.rejects(callBackend('reversePaymentRecord', { paymentId: '../users', reason: '误录' }), /记录编号无效/)
  // 生产 BOM 的启停用也只能使用受限的路径和编号。
  await callBackend('boms', undefined)
  assert.equal(calls[20].path, '/api/v1/boms')
  await callBackend('activateBom', { bomId: 12 })
  assert.equal(calls[21].path, '/api/v1/boms/12/activate')
  await assert.rejects(callBackend('retireBom', { bomId: '../users' }), /记录编号无效/)
  // 生产工单列表和下达操作也必须经过主进程的固定路径与正整数编号校验。
  await callBackend('workOrders', undefined)
  assert.equal(calls[22].path, '/api/v1/work-orders')
  await callBackend('releaseWorkOrder', { orderId: 13 })
  assert.equal(calls[23].path, '/api/v1/work-orders/13/release')
  await assert.rejects(callBackend('cancelWorkOrder', { orderId: '../users' }), /记录编号无效/)
  // 领料确认同样只允许固定业务路径，不能拼接外部传入的路径片段。
  await callBackend('materialIssues', undefined)
  assert.equal(calls[24].path, '/api/v1/material-issues')
  await callBackend('postMaterialIssue', { issueId: 14 })
  assert.equal(calls[25].path, '/api/v1/material-issues/14/post')
  await assert.rejects(callBackend('cancelMaterialIssue', { issueId: '../users' }), /记录编号无效/)
  // 退料确认沿受限接口访问固定路径，原领料编号和退料编号不可作为路径片段注入。
  await callBackend('materialReturns', undefined)
  assert.equal(calls[26].path, '/api/v1/material-returns')
  await callBackend('postMaterialReturn', { returnId: 15 })
  assert.equal(calls[27].path, '/api/v1/material-returns/15/post')
  await assert.rejects(callBackend('cancelMaterialReturn', { returnId: '../users' }), /记录编号无效/)
  // 完工质检只发送合格数量和说明，单据编号只用于受限路径。
  await callBackend('productionCompletions', undefined)
  assert.equal(calls[28].path, '/api/v1/production-completions')
  await callBackend('inspectProductionCompletion', { completionId: 16, accepted_quantity: '1', qc_note: '检验合格' })
  assert.equal(calls[29].path, '/api/v1/production-completions/16/inspect')
  assert.deepEqual(JSON.parse(calls[29].body), { accepted_quantity: '1', qc_note: '检验合格' })
  await callBackend('postProductionCompletion', { completionId: 16 })
  assert.equal(calls[30].path, '/api/v1/production-completions/16/post')
  await assert.rejects(callBackend('cancelProductionCompletion', { completionId: '../users' }), /记录编号无效/)
  await callBackend('reverseProductionCompletion', { completionId: 16, reason: '质检录错' })
  assert.equal(calls[31].path, '/api/v1/production-completions/16/reverse')
  assert.deepEqual(JSON.parse(calls[31].body), { reason: '质检录错' })
  await assert.rejects(callBackend('reverseProductionCompletion', { completionId: '../users', reason: '无效' }), /记录编号无效/)
  // 成本冲销只发送原因，领料核价和费用归集分别使用固定接口。
  await callBackend('productionCosts', undefined)
  assert.equal(calls[32].path, '/api/v1/production-costs')
  await callBackend('recordMaterialValuation', { material_issue_line_id: 17, unit_cost: '2.5', reference: 'INVOICE-1', note: '' })
  assert.equal(calls[33].path, '/api/v1/production-costs/material-valuations')
  await callBackend('recordProductionCharge', { work_order_id: 4, kind: 'labor', amount: '10', reference: 'LAB-1', note: '' })
  assert.equal(calls[34].path, '/api/v1/production-costs/charges')
  await callBackend('reverseProductionCost', { entryId: 18, reason: '记账错误' })
  assert.equal(calls[35].path, '/api/v1/production-costs/18/reverse')
  assert.deepEqual(JSON.parse(calls[35].body), { reason: '记账错误' })
  await assert.rejects(callBackend('reverseProductionCost', { entryId: '../users', reason: '无效' }), /记录编号无效/)
  // 盘点冲销沿固定路径提交原因，渲染层不能拼接任意后端地址。
  await callBackend('reverseStocktake', { stocktakeId: 19, reason: '实盘录错' })
  assert.equal(calls[36].path, '/api/v1/stocktakes/19/reverse')
  assert.deepEqual(JSON.parse(calls[36].body), { reason: '实盘录错' })
  await assert.rejects(callBackend('reverseStocktake', { stocktakeId: '../users', reason: '无效' }), /记录编号无效/)
  // 调拨冲销只能传原单编号和原因，路径由主进程限定。
  await callBackend('reverseTransfer', { transferId: 20, reason: '错选目标仓' })
  assert.equal(calls[37].path, '/api/v1/transfers/20/reverse')
  assert.deepEqual(JSON.parse(calls[37].body), { reason: '错选目标仓' })
  await assert.rejects(callBackend('reverseTransfer', { transferId: '../users', reason: '无效' }), /记录编号无效/)
  // 销售退货冲销只允许固定路径和原因，编号仍由主进程校验。
  await callBackend('reverseSalesReturn', { returnId: 21, reason: '退货录错' })
  assert.equal(calls[38].path, '/api/v1/sales-returns/21/reverse')
  assert.deepEqual(JSON.parse(calls[38].body), { reason: '退货录错' })
  await assert.rejects(callBackend('reverseSalesReturn', { returnId: '../users', reason: '无效' }), /记录编号无效/)
  // 采购退货冲销路径与原因由主进程限定，渲染层不能构造任意地址。
  await callBackend('reversePurchaseReturn', { returnId: 22, reason: '供应商未收货' })
  assert.equal(calls[39].path, '/api/v1/purchase-returns/22/reverse')
  assert.deepEqual(JSON.parse(calls[39].body), { reason: '供应商未收货' })
  await assert.rejects(callBackend('reversePurchaseReturn', { returnId: '../users', reason: '无效' }), /记录编号无效/)
  // 入库冲销只允许固定路径及原因，恶意编号不能穿越业务接口。
  await callBackend('reverseReceipt', { receiptId: 23, reason: '入库录错' })
  assert.equal(calls[40].path, '/api/v1/receipts/23/reverse')
  assert.deepEqual(JSON.parse(calls[40].body), { reason: '入库录错' })
  await assert.rejects(callBackend('reverseReceipt', { receiptId: '../users', reason: '无效' }), /记录编号无效/)
  // 出库冲销只能使用主进程限定的路径和编号，原因作为请求体传递。
  await callBackend('reverseShipment', { shipmentId: 24, reason: '出库录错' })
  assert.equal(calls[41].path, '/api/v1/shipments/24/reverse')
  assert.deepEqual(JSON.parse(calls[41].body), { reason: '出库录错' })
  await assert.rejects(callBackend('reverseShipment', { shipmentId: '../users', reason: '无效' }), /记录编号无效/)
  await assert.rejects(callBackend('confirmSalesOrder', { orderId: '../users' }), /记录编号无效/)
  await assert.rejects(callBackend('updateRole', { code: '../users', label: '错误', permissions: [] }), /角色代码无效/)
  // 权限名称更新仍经过固定操作和受限代码，页面不能拼接任意服务端路径。
  const permissionCallIndex = calls.length
  await callBackend('updatePermissionLabel', { code: 'inventory.view', label: '查看各仓库存量' })
  assert.equal(calls[permissionCallIndex].path, '/api/v1/permissions/inventory.view/label')
  assert.equal(calls[permissionCallIndex].method, 'PUT')
  assert.deepEqual(JSON.parse(calls[permissionCallIndex].body), { label: '查看各仓库存量' })
  await assert.rejects(callBackend('updatePermissionLabel', { code: '../users', label: '错误' }), /权限代码无效/)
  await assert.rejects(callBackend('postReceipt', { receiptId: '../users' }), /记录编号无效/)
  await assert.rejects(callBackend('unknown-operation', undefined), /不允许的业务操作/)
  await callBackend('logout', undefined)
  await assert.rejects(callBackend('me', undefined), /请先登录/)
  await callBackend('login', { username: 'admin', password: 'secure-pass-123' })
  await callBackend('changePassword', { current_password: 'old-password-123', new_password: 'new-password-123' })
  await assert.rejects(callBackend('me', undefined), /请先登录/)
  await callBackend('login', { username: 'admin', password: 'new-password-123' })
  fetchMock.mock.mockImplementation(async () => { throw new Error('connection refused') })
  await assert.rejects(callBackend('logout', undefined), /无法连接服务端/)
  await assert.rejects(callBackend('me', undefined), /请先登录/)
})


test('基础资料接口限定路径和正整数编号', async (t) => {
  const originalUrl = process.env.NEXORA_API_URL
  t.after(() => {
    if (originalUrl === undefined) delete process.env.NEXORA_API_URL
    else process.env.NEXORA_API_URL = originalUrl
  })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8000'
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    calls.push([new URL(url).pathname, init.method])
    return new Response(JSON.stringify(new URL(url).pathname === '/api/v1/materials/2' && init.method === 'PUT'
      ? { ...materialInput(materialDraft(), false), id: 2, sku: 'R', name: '电阻', version: 1 }
      : { token: 'test-token', user: { id: 1 } }), { status: 200 })
  })
  await callBackend('login', {})
  for (const [entity, resource] of [['Material', 'materials'], ['Supplier', 'suppliers'], ['Warehouse', 'warehouses']]) {
    for (const [verb, method] of [['update', 'PUT'], ['delete', 'DELETE']]) {
      const payload = verb === 'update'
        ? entity === 'Material' ? { id: 2, name: '电阻', unit: '件', version: 1 }
          : entity === 'Supplier' ? { id: 2, name: '供应商', version: 1, reason: '核对档案' }
            : { id: 2, code: 'EAST', name: '东仓', version: 1, reason: '核对档案' }
        : entity === 'Material' ? { id: 2 } : { id: 2, version: 1 }
      await callBackend(verb + entity, payload)
      assert.deepEqual(calls.at(-1), [`/api/v1/${resource}/2`, method])
      await assert.rejects(callBackend(verb + entity, { id: '../users' }), /记录编号无效/)
    }
  }
  await callBackend('bindSupplierMaterial', { supplierId: 3, materialId: 4 })
  assert.deepEqual(calls.at(-1), ['/api/v1/suppliers/3/materials/4', 'PUT'])
  await callBackend('unbindSupplierMaterial', { supplierId: 3, materialId: 4 })
  assert.deepEqual(calls.at(-1), ['/api/v1/suppliers/3/materials/4', 'DELETE'])
  await assert.rejects(callBackend('bindSupplierMaterial', { supplierId: 3, materialId: '../users' }), /记录编号无效/)
  await assert.rejects(callBackend('unbindSupplierMaterial', { supplierId: 0, materialId: 4 }), /记录编号无效/)
})

test('供应商和仓库审计接口只转发固定字段及版本', async (t) => {
  const originalUrl = process.env.NEXORA_API_URL
  t.after(() => {
    if (originalUrl === undefined) delete process.env.NEXORA_API_URL
    else process.env.NEXORA_API_URL = originalUrl
  })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8000'
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    calls.push({ path: `${new URL(url).pathname}${new URL(url).search}`, method: init.method, body: init.body })
    return Response.json({ token: 'test-token', user: { id: 1 } })
  })
  await callBackend('login', {})
  await callBackend('supplierDetail', { id: 4 })
  assert.equal(calls.at(-1).path, '/api/v1/suppliers/4')
  await callBackend('recentSupplierChanges', { before_id: 7 })
  assert.equal(calls.at(-1).path, '/api/v1/supplier-changes?before_id=7')
  await callBackend('warehouseChanges', { id: 8 })
  assert.equal(calls.at(-1).path, '/api/v1/warehouses/8/changes')
  await callBackend('updateSupplier', { id: 4, name: ' 甲厂 ', version: 2, reason: ' 修正 ', extra: '不转发' })
  assert.deepEqual(JSON.parse(calls.at(-1).body), { name: '甲厂', version: 2, reason: '修正' })
  await callBackend('updateWarehouse', { id: 8, code: 'east', name: ' 东仓 ', version: 3, reason: ' 改名 ', extra: true })
  assert.deepEqual(JSON.parse(calls.at(-1).body), { code: 'EAST', name: '东仓', version: 3, reason: '改名' })
  await callBackend('deleteWarehouse', { id: 8, version: 3 })
  assert.equal(calls.at(-1).path, '/api/v1/warehouses/8?version=3')
  await assert.rejects(callBackend('updateSupplier', { id: 4, name: '甲', version: 2, reason: '' }), /修改原因无效/)
  await assert.rejects(callBackend('deleteSupplier', { id: 4, version: '../users' }), /记录编号无效/)
  await assert.rejects(callBackend('recentWarehouseChanges', { before_id: '../users' }), /记录编号无效/)
})

test('采购申请操作使用固定路径且只发送正式字段', async (t) => {
  const originalUrl = process.env.NEXORA_API_URL
  t.after(() => {
    if (originalUrl === undefined) delete process.env.NEXORA_API_URL
    else process.env.NEXORA_API_URL = originalUrl
  })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8000'
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    calls.push({ path: new URL(url).pathname, method: init.method, body: init.body })
    return Response.json({ token: 'test-token', user: { id: 1 } })
  })
  await callBackend('login', {})
  await callBackend('purchaseRequests', undefined)
  assert.equal(calls.at(-1).path, '/api/v1/purchase-requests')
  const input = { requestId: 7, reference: 'REQ', note: '补货', lines: [{ material_id: 2, quantity: '3' }] }
  await callBackend('updatePurchaseRequest', input)
  assert.equal(calls.at(-1).path, '/api/v1/purchase-requests/7')
  assert.equal(calls.at(-1).method, 'PUT')
  assert.deepEqual(JSON.parse(calls.at(-1).body), { reference: 'REQ', note: '补货', lines: input.lines })
  await callBackend('rejectPurchaseRequest', { requestId: 7, reason: '数量错误' })
  assert.equal(calls.at(-1).path, '/api/v1/purchase-requests/7/reject')
  assert.deepEqual(JSON.parse(calls.at(-1).body), { reason: '数量错误' })
  await assert.rejects(callBackend('approvePurchaseRequest', { requestId: '../users' }), /记录编号无效/)
})

test('采购收货的确认和取消只能调用固定单据路径', async (t) => {
  const originalUrl = process.env.NEXORA_API_URL
  t.after(() => {
    if (originalUrl === undefined) delete process.env.NEXORA_API_URL
    else process.env.NEXORA_API_URL = originalUrl
  })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8000'
  const paths = []
  t.mock.method(globalThis, 'fetch', async (url) => {
    paths.push(new URL(url).pathname)
    return Response.json({ token: 'test-token', user: { id: 1 } })
  })
  await callBackend('login', {})
  await callBackend('goodsReceipts', undefined)
  await callBackend('confirmGoodsReceipt', { goodsReceiptId: 3 })
  assert.deepEqual(paths.slice(-2), ['/api/v1/purchase-goods-receipts',
    '/api/v1/purchase-goods-receipts/3/confirm'])
  await assert.rejects(callBackend('cancelGoodsReceipt', { goodsReceiptId: '../users' }), /记录编号无效/)
})

test('其他入库冲销只转发固定路径与原因', async (t) => {
  const originalUrl = process.env.NEXORA_API_URL
  t.after(() => {
    if (originalUrl === undefined) delete process.env.NEXORA_API_URL
    else process.env.NEXORA_API_URL = originalUrl
  })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8000'
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    calls.push({ path: new URL(url).pathname, body: init.body })
    return Response.json({ token: 'test-token', user: { id: 1 } })
  })
  await callBackend('login', {})
  await callBackend('reverseOtherInbound', { inboundId: 4, reason: '误录' })
  assert.equal(calls.at(-1).path, '/api/v1/warehouse-inbounds/4/reverse')
  assert.deepEqual(JSON.parse(calls.at(-1).body), { reason: '误录' })
  await assert.rejects(callBackend('postOtherInbound', { inboundId: '../users' }), /记录编号无效/)
  // 重开使用专用接口，来源编号在路径，正文不带原审批或历史记录。
  await callBackend('reopenOtherInbound',{inboundId:4,warehouse_id:1,reason:'gift',note:'更正',reference:'REF',lines:[{material_id:2,quantity:'3'}]})
  assert.equal(calls.at(-1).path,'/api/v1/warehouse-inbounds/4/reopen')
  assert.deepEqual(JSON.parse(calls.at(-1).body),{warehouse_id:1,reason:'gift',note:'更正',reference:'REF',lines:[{material_id:2,quantity:'3'}]})
  await assert.rejects(callBackend('reopenOtherInbound',{inboundId:'../users'}),/记录编号无效/)

})

test('供应商分页通过桌面接口原样发送查询参数并保留分页元数据', async t => {
  // 验证 IPC 到 HTTP 的契约，不依赖前端预览中的临时桥接。
  const originalUrl = process.env.NEXORA_API_URL
  t.after(() => {
    if (originalUrl === undefined) delete process.env.NEXORA_API_URL
    else process.env.NEXORA_API_URL = originalUrl
  })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8123'
  const query = { query: '工厂', page: 2, page_size: 10 }
  const result = { items: [{ id: 11, name: '工厂 11' }], total: 11, page: 2, page_size: 10 }
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    if (url.pathname.endsWith('/login')) return Response.json({ token: 'test-token', user: { id: 1 } })
    assert.equal(url.pathname, '/api/v1/suppliers/query')
    assert.equal(options.method, 'POST')
    assert.deepEqual(JSON.parse(options.body), query)
    return Response.json(result)
  })
  await callBackend('login', {})
  assert.deepEqual(await callBackend('querySuppliers', query), result)
})
