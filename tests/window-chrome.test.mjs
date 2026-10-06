import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { test } from 'node:test'
import ts from 'typescript'
import { windowChromeOptions } from '../src/main/window-chrome.ts'
import { usesIntegratedTitleBar, windowOverlayTheme } from '../src/shared/window-chrome.ts'

test('窗口控件保持 Mac 左侧和 Windows 原生位置，其他平台不改变窗口外框', () => {
  assert.deepEqual(windowChromeOptions('darwin'), {
    titleBarStyle: 'hidden', titleBarOverlay: true, trafficLightPosition: { x: 16, y: 17 }
  })
  assert.deepEqual(windowChromeOptions('win32'), {
    titleBarStyle: 'hidden', titleBarOverlay: { color: '#00000000', symbolColor: '#17213b', height: 48 }
  })
  assert.deepEqual(windowChromeOptions('linux'), {})
  assert.equal(usesIntegratedTitleBar(undefined), false)
  assert.equal(usesIntegratedTitleBar('browser'), false)
})

test('窗口主题只接受既定主题，不能注入任意原生窗口参数', () => {
  assert.deepEqual(windowOverlayTheme('dark'), { color: '#00000000', symbolColor: '#e6edf8', height: 48 })
  for (const invalid of [undefined, null, '', 'system', {}, { color: '#ff0000' }, true]) {
    assert.throws(() => windowOverlayTheme(invalid), /窗口主题参数无效/)
  }
})

test('Windows 首次创建与反复切换主题都保持透明背景，不覆盖弹窗遮罩和顶部栏底线', () => {
  // 明确检查 alpha 为零，防止把“与顶部同色”误当作能与遮罩融合。
  const initial = windowChromeOptions('win32').titleBarOverlay
  for (const overlay of [initial, ...['dark', 'light', 'dark'].map(windowOverlayTheme)]) {
    assert.equal(overlay.color, '#00000000')
    assert.equal(Number.parseInt(overlay.color.slice(7, 9), 16), 0)
    assert.equal(overlay.height, 48)
  }
  assert.notEqual(windowOverlayTheme('light').symbolColor, windowOverlayTheme('dark').symbolColor)
})

// 执行实际 IPC 处理器，验证来源校验和两种平台的主题更新行为。
const source = readFileSync(new URL('../src/main/index.ts', import.meta.url), 'utf8')
const ast = ts.createSourceFile('index.ts', source, ts.ScriptTarget.Latest, true)
const guard = ast.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'assertMainWindow')
let handler
function visit(node) {
  if (ts.isCallExpression(node) && node.expression.getText(ast) === 'ipcMain.handle'
    && node.arguments[0]?.text === 'window:set-theme') handler = node.arguments[1]
  ts.forEachChild(node, visit)
}
visit(ast)
assert.ok(guard && handler)
const script = ts.transpileModule(`${guard.getText(ast)}; const handle = ${handler.getText(ast)};`, {
  compilerOptions: { target: ts.ScriptTarget.ES2022 }
}).outputText

for (const platform of ['darwin', 'win32']) {
  test(`${platform} 主题通道拒绝其他窗口、子框架和非法参数`, () => {
    const calls = []
    const webContents = { mainFrame: {} }
    const mainWindow = { webContents, setTitleBarOverlay: value => calls.push(value) }
    const context = { mainWindow, windowOverlayTheme, process: { platform } }
    const invoke = (event, mode) => runInNewContext(`${script}\nhandle(event, mode)`, { ...context, event, mode })
    const event = { sender: webContents, senderFrame: webContents.mainFrame }
    invoke(event, 'dark')
    invoke(event, 'light')
    assert.deepEqual(calls, platform === 'win32' ? [windowOverlayTheme('dark'), windowOverlayTheme('light')] : [])
    assert.throws(() => invoke({ sender: {}, senderFrame: webContents.mainFrame }, 'dark'), /不允许的窗口请求/)
    assert.throws(() => invoke({ sender: webContents, senderFrame: {} }, 'dark'), /不允许的窗口请求/)
    assert.throws(() => invoke(event, 'invalid'), /窗口主题参数无效/)
    context.mainWindow = null
    assert.throws(() => invoke(event, 'dark'), /不允许的窗口请求/)
  })
}
