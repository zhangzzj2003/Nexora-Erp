import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { test } from 'node:test'
import { hasWorkspaceSelection, resolveWorkspaceSelection, workspaceSelectKey } from '../src/renderer/src/utils/workspace-select.ts'

// 编号、字符串和空值同样可能出现在筛选中，回传时必须保持它们各自的类型。
test('下拉选择区分数字、字符串、布尔值、空字符串和全部选项', () => {
  const values = [1, '1', 0, '0', true, false, 'true', null, 'null', '']
  const options = values.map(value => ({ label: String(value), value }))
  assert.equal(new Set(values.map(workspaceSelectKey)).size, values.length)
  for (const value of values) {
    assert.equal(resolveWorkspaceSelection(options, workspaceSelectKey(value)).value, value)
  }
})

test('不可选占位、禁用控件和过期菜单事件不会更新业务状态', () => {
  const options = [{ label: '选择物料', value: 0, disabled: true }, { label: '物料 A', value: 8 }]
  assert.equal(resolveWorkspaceSelection(options, workspaceSelectKey(0)), undefined)
  assert.equal(resolveWorkspaceSelection(options, workspaceSelectKey(8), true), undefined)
  assert.equal(resolveWorkspaceSelection(options, workspaceSelectKey(9)), undefined)
  for (const malformed of [null, undefined, 8, [], {}, '8']) {
    assert.equal(resolveWorkspaceSelection(options, malformed), undefined)
  }
})

test('必填区分合法全部选项与占位，并在选项删除后恢复无效状态', () => {
  assert.equal(hasWorkspaceSelection([{ label: '全部仓库', value: 0 }], 0), true)
  assert.equal(hasWorkspaceSelection([{ label: '全部来源', value: null }], null), true)
  assert.equal(hasWorkspaceSelection([{ label: '请选择', value: 0, disabled: true }], 0), false)
  assert.equal(hasWorkspaceSelection([], 8), false)
  assert.equal(hasWorkspaceSelection([{ label: '编号字符串', value: '8' }], 8), false)
  assert.equal(hasWorkspaceSelection([{ label: '停用', value: false }], false), true)
})

// 防止页面直接使用原生或 Naive 下拉；单选与供应商可创建多选均从公共封装入口渲染。
test('所有工作台页面与公共表格都通过公共封装使用下拉选择', () => {
  // URL 转成本机路径，兼容 Windows 盘符及包含空格的工作区。
  const root = fileURLToPath(new URL('../src/renderer/src/', import.meta.url))
  function files(directory) {
    return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
      const path = join(directory, entry.name)
      return entry.isDirectory() ? files(path) : path.endsWith('.vue') ? [path] : []
    })
  }
  for (const file of files(root)) {
    if (file === join(root, 'components/workspace/WorkspaceSelect.vue')
      || file === join(root, 'components/workspace/WorkspaceSupplierSelect.vue')) continue
    assert.doesNotMatch(readFileSync(file, 'utf8'), /<(?:select|NSelect|n-select)\b/, file)
  }
})
