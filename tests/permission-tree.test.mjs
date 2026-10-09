import assert from 'node:assert/strict'
import test from 'node:test'
import {
  buildPermissionTree,
  documentPermissionCodes,
  documentPermissionGroups,
  modulePermissionCodes,
  operationGroupPermissionCodes,
  selectedPermissionCount,
  togglePermissionCodes
} from '../src/renderer/src/utils/permission-tree.ts'

test('同名审批按钮按单据分成独立的操作叶子', () => {
  const permissions = [
    { code: 'receipt.approve', label: '批准', group_path: [
      { code: 'warehouse', label: '仓库管理' }, { code: 'receipt', label: '入库单' }] },
    { code: 'shipment.approve', label: '批准', group_path: [
      { code: 'warehouse', label: '仓库管理' }, { code: 'shipment', label: '出库单' }] },
    { code: 'receipt.review', label: '审核', group_path: [
      { code: 'warehouse', label: '仓库管理' }, { code: 'receipt', label: '入库单' }] }
  ]
  const [warehouse] = buildPermissionTree(permissions)
  assert.equal(warehouse.label, '仓库管理')
  assert.equal(warehouse.documents.length, 2)
  const receipt = warehouse.documents.find((document) => document.code === 'receipt')
  const shipment = warehouse.documents.find((document) => document.code === 'shipment')
  assert.deepEqual(new Set(documentPermissionCodes(receipt)), new Set(['receipt.approve', 'receipt.review']))
  assert.deepEqual(documentPermissionCodes(shipment), ['shipment.approve'])

  const selected = togglePermissionCodes([], documentPermissionCodes(receipt), true)
  assert.deepEqual(new Set(selected), new Set(['receipt.approve', 'receipt.review']))
  assert.equal(selected.includes('shipment.approve'), false)
  assert.equal(selectedPermissionCount(selected, modulePermissionCodes(warehouse)), 2)
  assert.deepEqual(togglePermissionCodes(selected, ['receipt.approve'], false), ['receipt.review'])
})

test('旧服务端缺少层级字段时仍显示权限叶子', () => {
  const [fallback] = buildPermissionTree([{ code: 'legacy.view', label: '查看旧单据' }])
  assert.equal(fallback.label, '其他权限')
  assert.deepEqual(documentPermissionCodes(fallback.documents[0]), ['legacy.view'])
})

test('读写与审核按操作代码分开，改名和业务确认不影响分类', () => {
  // 故意交换中文含义，确保权限目录改名不会改变操作类别。
  const document = { code: 'other_inbound', label: '其他入库', permissions: [
    { code: 'other_inbound.view', label: '审核查看说明' },
    { code: 'other_inbound.create', label: '创建' },
    { code: 'other_inbound.post', label: '确认' },
    { code: 'other_inbound.reverse', label: '冲销' },
    { code: 'other_inbound.cancel', label: '取消' },
    { code: 'other_inbound.review', label: '自定义一' },
    { code: 'other_inbound.verify', label: '自定义二' },
    { code: 'other_inbound.approve', label: '自定义三' },
    { code: 'production_completion.inspect', label: '检验' },
    { code: 'future.preview', label: '预览' }
  ] }
  const before = structuredClone(document)
  const [readWrite, approval] = documentPermissionGroups(document)
  assert.equal(readWrite.label, '读写操作')
  assert.equal(approval.label, '审核操作')
  assert.deepEqual(operationGroupPermissionCodes(approval), ['other_inbound.review', 'other_inbound.verify', 'other_inbound.approve'])
  assert.equal(readWrite.permissions.length, 7)
  assert.deepEqual(document, before)
  assert.deepEqual(new Set([...operationGroupPermissionCodes(readWrite), ...operationGroupPermissionCodes(approval)]), new Set(documentPermissionCodes(document)))
  // 分类全选只影响本类，保留其他单据和未知的历史授权代码。
  const selected = togglePermissionCodes(['shipment.review', 'legacy.unknown'], operationGroupPermissionCodes(readWrite), true)
  assert.equal(selectedPermissionCount(selected, operationGroupPermissionCodes(approval)), 0)
  const partial = togglePermissionCodes(selected, ['other_inbound.review'], true)
  assert.equal(selectedPermissionCount(partial, operationGroupPermissionCodes(approval)), 1)
  assert.deepEqual(togglePermissionCodes(partial, operationGroupPermissionCodes(readWrite), false), ['shipment.review', 'legacy.unknown', 'other_inbound.review'])
})

test('空分类不展示，旧权限和未知操作不丢失', () => {
  // 兼容没有模块层级的旧目录；空单据不会制造可以提交的分类权限代码。
  const [module] = buildPermissionTree([{ code: 'legacy.view', label: '查看' }, { code: 'legacy.review', label: '审核' }])
  assert.deepEqual(documentPermissionGroups(module.documents[0]).map(group => group.code), ['read-write', 'approval'])
  assert.deepEqual(documentPermissionGroups({ permissions: [] }), [])
  assert.deepEqual(documentPermissionGroups({ permissions: [{ code: 'receipt.approve', label: '批准' }] }).map(group => group.code), ['approval'])
  assert.deepEqual(documentPermissionGroups({ permissions: [{ code: 'unknown', label: '未知' }] }).map(group => group.code), ['read-write'])
})
