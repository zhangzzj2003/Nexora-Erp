import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { test } from 'node:test'
import { createSSRApp, h } from 'vue'
import { setup as setupSsrStyles } from '@css-render/vue3-ssr'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { normalizeInputValue } from '../src/renderer/src/utils/input-value.ts'

// 空输入不转成零，金额仍为字符串；显式数字模型保留端口和编号的类型。
test('输入转换保留业务字段类型并处理清空、空格和非法数字', () => {
  assert.equal(normalizeInputValue(' 12.50 ', '0', { trim: true }), '12.50')
  assert.equal(normalizeInputValue('65535', 7001), 65535)
  assert.equal(normalizeInputValue('12', '', { number: true }), 12)
  assert.equal(normalizeInputValue('', 7001), '')
  assert.equal(normalizeInputValue('bad', 7001), 'bad')
  assert.equal(normalizeInputValue('Infinity', 7001), 'Infinity')
  assert.equal(normalizeInputValue(' pwd ', '', {}), ' pwd ')
})

test('公共按钮保留提交类型、禁用/加载保护以及图标和读屏属性', async t => {
  const server = await createServer({ configFile: false, plugins: [vue()],
    optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  t.after(() => server.close())
  const { default: AppButton } = await server.ssrLoadModule('/src/renderer/src/components/app/AppButton.vue')
  const { default: AppInput } = await server.ssrLoadModule('/src/renderer/src/components/app/AppInput.vue')
  const render = (component, props, slots) => {
    const app = createSSRApp({ render: () => h(component, props, slots) })
    setupSsrStyles(app)
    return renderToString(app)
  }
  const plain = await render(AppButton, { 'aria-label': '编辑资料' }, { default: () => '编辑', icon: () => h('svg', { 'aria-hidden': true }) })
  assert.match(plain, /type="button"/)
  assert.match(plain, /aria-label="编辑资料"/)
  assert.match(plain, /<svg/)
  assert.doesNotMatch(plain, /\sdisabled(?:\s|>)/)
  assert.match(await render(AppButton, { type: 'submit', variant: 'primary' }), /type="submit"/)
  assert.match(await render(AppButton, { type: 'reset' }), /type="reset"/)
  for (const props of [{ disabled: true }, { loading: true }]) {
    assert.match(await render(AppButton, props), /\sdisabled(?:\s|>)/)
  }
  // NInput 的包装不能吞掉浏览器必填、数字范围、步长、长度和输入语义。
  const number = await render(AppInput, { modelValue: '1.25', type: 'number', required: true, min: '0.001', max: '100', step: '0.001', 'aria-label': '数量' })
  const input = number.match(/<input\b[^>]*>/)?.[0] ?? ''
  for (const pattern of [/type="number"/, /required/, /min="0.001"/, /max="100"/, /step="0.001"/, /aria-label="数量"/]) assert.match(input, pattern)
  const text = await render(AppInput, { modelValue: '', maxlength: 100, pattern: '[0-9]+', disabled: true })
  assert.match(text, /maxlength="100"/)
  assert.match(text, /pattern="\[0-9\]\+"/)
  assert.match(text, /\sdisabled(?:\s|>)/)
  // 系统编码需要可以选中复制但不能输入，必须传给 NInput 的正式只读属性。
  const readonly = await render(AppInput, { modelValue: 'EL-SR-000001', readonly: true })
  assert.match(readonly.match(/<input\b[^>]*>/)?.[0] ?? '', /\sreadonly(?:\s|>)/)
  assert.doesNotMatch(readonly.match(/<input\b[^>]*>/)?.[0] ?? '', /\sdisabled(?:\s|>)/)
  const evidence = await render(AppInput, { modelValue: '', type: 'textarea', rows: 3,
    required: true, minlength: 10, maxlength: 500, 'aria-label': '现场核对依据' })
  const textarea = evidence.match(/<textarea\b[^>]*>/)?.[0] ?? ''
  for (const pattern of [/rows="3"/, /required/, /minlength="10"/, /maxlength="500"/,
    /aria-label="现场核对依据"/]) assert.match(textarea, pattern)
})

test('隐藏数字步进按钮不改变原生数量边界，且只作用于显式启用的数字框', async t => {
  const server = await createServer({ configFile: false, plugins: [vue()],
    optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  t.after(() => server.close())
  const { default: AppInput } = await server.ssrLoadModule('/src/renderer/src/components/app/AppInput.vue')
  const render = props => {
    const app = createSSRApp({ render: () => h(AppInput, props) })
    setupSsrStyles(app)
    return renderToString(app)
  }
  const quantity = { modelValue: '1.001', type: 'number', required: true,
    min: '0.001', max: '1000000', step: '0.001', 'aria-label': '物料数量', class: 'quantity-field' }
  const hidden = await render({ ...quantity, hideNumberControls: true })
  assert.match(hidden, /app-input--no-number-controls/)
  assert.match(hidden, /quantity-field/)
  // 检查真实 input，避免包装层隐藏按钮时意外转成文本框或吞掉校验属性。
  const input = hidden.match(/<input\b[^>]*>/)?.[0] ?? ''
  for (const pattern of [/type="number"/, /value="1.001"/, /required/, /min="0.001"/,
    /max="1000000"/, /step="0.001"/, /aria-label="物料数量"/]) assert.match(input, pattern)
  assert.doesNotMatch(input, /hide-?number-?controls/i)
  for (const props of [quantity, { ...quantity, hideNumberControls: false },
    { modelValue: '名称', type: 'text', hideNumberControls: true }]) {
    assert.doesNotMatch(await render(props), /app-input--no-number-controls/)
  }
  const locked = await render({ ...quantity, hideNumberControls: true, disabled: true, readonly: true })
  const lockedInput = locked.match(/<input\b[^>]*>/)?.[0] ?? ''
  assert.match(lockedInput, /\sdisabled(?:\s|>)/)
  assert.match(lockedInput, /\sreadonly(?:\s|>)/)
})

test('页面统一使用公共控件，只保留选择校验代理和表格专用滚动条', () => {
  const root = fileURLToPath(new URL('../src/renderer/src/', import.meta.url))
  function files(directory) {
    return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
      const path = join(directory, entry.name)
      return entry.isDirectory() ? files(path) : path.endsWith('.vue') ? [path] : []
    })
  }
  for (const file of files(root)) {
    const source = readFileSync(file, 'utf8')
    if (!file.endsWith('AppInput.vue')) assert.doesNotMatch(source, /<(?:NInput|n-input)\b/, file)
    if (!file.endsWith('AppButton.vue')) assert.doesNotMatch(source, /<(?:button|NButton|n-button)\b/, file)
    if (!file.endsWith('WorkspaceSelect.vue') && !file.endsWith('WorkspaceTable.vue')) assert.doesNotMatch(source, /<(?:input|select|textarea|details|summary)\b/, file)
  }
})
