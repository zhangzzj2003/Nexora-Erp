import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import postcss from 'postcss'
import { themeColorPresets, isThemeColor, readThemeColor, saveThemeColor, themeColorPalette, themeColorVariables } from '../src/renderer/src/utils/theme-color.ts'
import { appThemeOverrides } from '../src/renderer/src/utils/app-theme.ts'
import { workspaceSelectTheme } from '../src/renderer/src/utils/workspace-select.ts'

test('固定预设支持独立存取，损坏或被阻止的偏好回退默认青绿', () => {
  // 固定完整名单，同时锁定旧键兼容和新增颜色可用，避免仅校验数量而遗漏原有偏好。
  const keys = ['teal', 'green', 'cyan', 'blue', 'indigo', 'violet', 'fuchsia', 'rose', 'red', 'orange', 'amber', 'slate']
  assert.deepEqual(themeColorPresets.map(preset => preset.key), keys)
  assert.equal(new Set(keys).size, 12)
  for (const value of [null, '', 'invalid', '#ff0000', 'url(test)', {}, undefined]) {
    assert.equal(isThemeColor(value), false)
    assert.equal(readThemeColor({ getItem: () => value }), 'teal')
  }
  assert.equal(readThemeColor(), 'teal')
  assert.equal(readThemeColor({ getItem() { throw new Error('blocked') } }), 'teal')
  assert.doesNotThrow(() => saveThemeColor({ setItem() { throw new Error('blocked') } }, 'blue'))
  const values = new Map(), storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) }
  for (const preset of themeColorPresets) {
    saveThemeColor(storage, preset.key)
    assert.equal(readThemeColor(storage), preset.key)
    assert.equal(values.size, 1)
  }
})

test('扩展色卡保留原有六种颜色的存储键和明暗色值', () => {
  // 已保存的主题无需迁移；旧键恢复后也不能悄悄变成其他色调。
  const previous = [
    ['teal', '#237d7a', '#78d6cd'], ['blue', '#2563eb', '#93c5fd'],
    ['indigo', '#4f46e5', '#a5b4fc'], ['violet', '#7c3aed', '#c4b5fd'],
    ['amber', '#b45309', '#fcd34d'], ['rose', '#be185d', '#f9a8d4']
  ]
  for (const [key, primary, darkAccent] of previous) {
    const preset = themeColorPresets.find(item => item.key === key)
    assert.ok(preset, key)
    assert.equal(preset.primary, primary)
    assert.equal(preset.darkAccent, darkAccent)
    assert.equal(readThemeColor({ getItem: () => key }), key)
  }
})

// 对真实色值计算 WCAG 对比度，避免预设切换后按钮白字或强调文字不可读。
function luminance(hex) {
  return [1, 3, 5].map(offset => parseInt(hex.slice(offset, offset + 2), 16) / 255)
    .map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4)
    .reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0)
}
function contrast(a, b) {
  const values = [luminance(a), luminance(b)].sort((a, b) => b - a)
  return (values[0] + .05) / (values[1] + .05)
}
test('全部预设适配两种模式，按钮状态和导航文字保持可读且菜单同步配色', () => {
  for (const preset of themeColorPresets) for (const dark of [false, true]) {
    const palette = themeColorPalette(preset.key, dark), variables = themeColorVariables(palette)
    for (const state of ['primary', 'hover', 'pressed'])
      assert.ok(contrast(palette[state], '#ffffff') >= 4.5, `${preset.key}/${state}`)
    for (const surface of [palette.tint, palette.activeTint, dark ? '#16253a' : '#ffffff'])
      assert.ok(contrast(palette.accent, surface) >= 4.5, `${preset.key}/${dark}/${surface}`)
    assert.equal(variables['--workspace-field-accent'], palette.accent)
    assert.equal(variables['--app-button-primary'], preset.primary)
    assert.equal(appThemeOverrides(palette).common.primaryColor, palette.accent)
    const peers = workspaceSelectTheme(dark, palette).peers
    assert.equal(peers.InternalSelection.borderFocus, `1px solid ${palette.accent}`)
    assert.equal(peers.InternalSelectMenu.optionCheckColor, palette.accent)
    assert.equal(peers.InternalSelectMenu.optionColorActive, palette.tint)
  }
})

// 直接检查正式 CSS 的完整规则集，防止明暗覆盖规则再次把共享图标锁定为某个颜色。
function cssRules(path) {
  const source = readFileSync(new URL(`../src/renderer/src/${path}`, import.meta.url), 'utf8')
  const css = path.endsWith('.vue')
    ? [...source.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map(match => match[1]).join('\n') : source
  const rules = []
  postcss.parse(css).walkRules(rule => rules.push(rule))
  return rules
}
function declarations(rule) {
  return Object.fromEntries(rule.nodes.filter(node => node.type === 'decl').map(node => [node.prop, node.value]))
}

test('共享空状态图标继承主题色，深色覆盖不能恢复固定青绿，错误图标保留红色', () => {
  const rules = cssRules('components/workspace/WorkspaceTable.vue')
  const normal = rules.filter(rule => rule.selector.includes('.workspace-table-empty-icon') && !rule.selector.includes('.is-error'))
  assert.ok(normal.length > 0)
  const base = declarations(normal.find(rule => rule.selector === '.workspace-table-empty-icon'))
  assert.equal(base.color, 'var(--workspace-field-accent)')
  assert.equal(base.background, 'var(--app-accent-tint)')
  assert.equal(base.border, '1px solid var(--app-accent-ring)')
  for (const rule of normal) for (const [key, value] of Object.entries(declarations(rule))) {
    if (/^(color|background(?:-color)?|border(?:-color)?)$/.test(key))
      assert.match(value, /var\(--(?:workspace-field-accent|app-accent-tint|app-accent-ring)\)/, rule.selector)
  }
  const errors = rules.filter(rule => rule.selector.includes('.workspace-table-empty-icon') && rule.selector.includes('.is-error'))
  assert.equal(errors.length, 2)
  assert.deepEqual(errors.map(rule => declarations(rule).color), ['#c45a53', '#ffaaa2'])
  const source = readFileSync(new URL('../src/renderer/src/components/workspace/WorkspaceTable.vue', import.meta.url), 'utf8')
  assert.match(source, /stroke="currentColor"/)
})

test('账号与引导装饰图标跟随强调色，成功和离线图标保持状态色', () => {
  const rules = ['style.css', 'light-theme.css', 'dark-theme.css'].flatMap(cssRules)
  const avatar = declarations(rules.find(rule => rule.selector === '.sidebar-account-avatar'))
  assert.match(avatar.background, /var\(--app-button-primary\)/)
  assert.match(avatar.background, /var\(--app-button-primary-pressed\)/)
  // 白色头像轮廓依靠主色底保持对比度，前面的全部预设测试也覆盖渐变两端。
  assert.equal(avatar.color, '#fff')
  for (const selector of ['.sidebar-account-menu svg', '.trust-icon']) {
    const icons = rules.filter(rule => rule.selector.includes(selector))
    assert.ok(icons.length > 0)
    for (const rule of icons) {
      const values = declarations(rule)
      if (values.color) assert.equal(values.color, 'var(--workspace-field-accent)')
      if (values.background) assert.equal(values.background, 'var(--app-accent-tint)')
    }
  }
  for (const selector of ['.ready-symbol', '.offline-symbol']) {
    for (const rule of rules.filter(rule => rule.selector.includes(selector))) {
      for (const value of Object.values(declarations(rule))) assert.doesNotMatch(value, /var\(--(?:app-accent|workspace-field-accent)/)
    }
  }
})
