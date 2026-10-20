// 用真实 Chromium 验证布局、焦点与 WAAPI；运行时传入已安装 Playwright 的入口，不增加产品依赖。
import assert from 'node:assert/strict'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { mkdir, mkdtemp, writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { pathToFileURL } from 'node:url'
const modulePath = process.env.NEXORA_PLAYWRIGHT_MODULE
if (!modulePath) throw Error('请设置 NEXORA_PLAYWRIGHT_MODULE 为已安装的 playwright 入口。')
const { chromium, _electron } = await import(pathToFileURL(modulePath).href)
const fixture = `
import {createApp,h,ref,nextTick,onUnmounted,getCurrentInstance} from 'vue';
import {NMessageProvider} from 'naive-ui';
import AppModal from '/src/renderer/src/components/app/AppModal.vue';
import {captureDialogOrigin} from '/src/renderer/src/utils/dialog-origin.ts';
import {useDialogPreparation,invalidateDialogPresentations} from '/src/renderer/src/composables/use-dialog-presentation.ts';
const show=ref(false),ready=ref(false),error=ref(''),row=ref('Original complete record'),history=ref(true),nested=ref(false),nestedReady=ref(false),busy=ref(false);window.afterLeaves=0;
window.historyMounts=0;window.historyEvents=[];const History={setup(){window.historyMounts++;window.historyEvents.push('mount '+performance.now()+' '+(()=>{let p=getCurrentInstance(),a=[];while(p){a.push((p.type.name||'anon')+':'+p.uid);p=p.parent}return a.join('/');})());onUnmounted(()=>window.historyEvents.push('unmount '+performance.now()));useDialogPreparation(history);return()=>h('p','History ready: '+!history.value)}};
window.dialogFixture={show,ready,error,row,history,nested,nestedReady,busy,nextTick,invalidate:invalidateDialogPresentations};
const content=()=>h('div',{class:'fixture-content'},[h('p',{class:'record'},row.value),h('p',{class:'css-evidence'},'CSS animation evidence'),h(History),
 h('input',{id:'private-input',name:'private-input',value:row.value}),h('textarea',{id:'private-note',value:'typed note'}),
 h('div',{class:'scroll',style:'height:80px;overflow:auto'},[h('div',{style:'height:400px'},'scroll evidence')]),
 h('button',{id:'nested-trigger',onClick:e=>{captureDialogOrigin('nested',e);nested.value=true}},'Nested')]);
createApp({setup(){return()=>h(NMessageProvider,null,{default:()=>[
 h('button',{id:'open',onClick:e=>{captureDialogOrigin('primary',e);show.value=true}},'Open details'),
 h('button',{id:'open-other',style:'margin-left:120px',onClick:e=>{captureDialogOrigin('primary',e);show.value=true}},'Open other'),
 h(AppModal,{show:show.value,busy:busy.value,ready:ready.value,loadError:error.value,originKey:'primary',preset:'card',title:'Details',style:{width:'600px'},
 onAfterLeave:()=>window.afterLeaves++,'onUpdate:show':v=>{show.value=v;if(!v)row.value=''}}, {default:content}),
 h(AppModal,{show:nested.value,busy:busy.value,ready:nestedReady.value,originKey:'nested',preset:'card',title:'Nested details',style:{width:'320px'},'onUpdate:show':v=>nested.value=v},
 {default:()=>h('button',{id:'close-nested',onClick:()=>nested.value=false},'Close nested')})
]})}}).mount('#app');
window.dialogFrames=[];function sample(){const el=document.querySelector('[data-app-modal-id]');if(el&&getComputedStyle(el).visibility==='visible'&&+getComputedStyle(el).opacity>.05)window.dialogFrames.push({phase:el.dataset.dialogPhase,text:el.textContent});requestAnimationFrame(sample)}requestAnimationFrame(sample);
`
const server = await createServer({ configFile: false, plugins: [vue(), {
  name: 'dialog-motion-browser-fixture',
  resolveId: id => id === '/dialog-fixture.js' ? '\0dialog-fixture' : undefined,
  load: id => id === '\0dialog-fixture' ? fixture : undefined,
  configureServer(server) { server.middlewares.use((req, res, next) => {
    if (req.url !== '/') return next()
    res.setHeader('content-type', 'text/html'); res.end('<html><head><style>@keyframes evidence-fade{from{opacity:.1}to{opacity:1}}@keyframes evidence-draw{from{width:0}to{width:120px}}.css-evidence{animation:evidence-fade 2s 120ms both}.css-evidence::before{content:"";display:block;height:3px;background:#246;animation:evidence-draw 2s 120ms both}body{font:14px sans-serif;margin:40px}#open{margin:40px;padding:12px}:root{--app-modal-surface:white;--workspace-field-border:#ddd;--workspace-field-accent:#246}</style></head><body><div id="app"></div><script type="module" src="/dialog-fixture.js"></script></body></html>')
  }) }
}], server: { host: '127.0.0.1', port: 0 }, appType: 'custom' })
await server.listen()
let browser, electron, electronDirectory
try {
  const electronMode = process.env.NEXORA_DIALOG_ENGINE === 'electron'
  let page
  if (electronMode) {
    electronDirectory = await mkdtemp(join(tmpdir(), 'nexora-dialog-electron-'))
    const mainPath = join(electronDirectory, 'main.cjs')
    await writeFile(mainPath, `const {app,BrowserWindow}=require('electron');app.setPath('userData',${JSON.stringify(join(electronDirectory, 'profile'))});app.whenReady().then(()=>{const win=new BrowserWindow({width:1280,height:900,useContentSize:true,webPreferences:{contextIsolation:true,nodeIntegration:false}});win.loadURL(${JSON.stringify(server.resolvedUrls.local[0])})});`)
    const { default: electronPath } = await import('electron')
    electron = await _electron.launch({ executablePath: electronPath, args: [mainPath] })
    page = await electron.firstWindow()
  } else {
    browser = await chromium.launch({ headless: true, channel: process.env.NEXORA_CHROMIUM_CHANNEL || 'chrome' })
    page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  }
  const evidenceDir = process.env.NEXORA_DIALOG_EVIDENCE_DIR
  if (evidenceDir) await mkdir(evidenceDir, { recursive: true })
  const evidence = async name => { if (evidenceDir) await page.screenshot({ path: join(evidenceDir, name + '.png'), fullPage: true }) }
  const errors = []; page.on('pageerror', error => errors.push(error.message))
  await page.goto(server.resolvedUrls.local[0]); await page.waitForSelector('#open')
  await page.click('#open'); await page.waitForTimeout(60)
  assert.equal(await page.locator('.n-modal-mask:visible').count(), 0, '准备期不出现遮罩')
  assert.equal(await page.locator('[data-app-modal-id]').evaluate(el => getComputedStyle(el).visibility), 'hidden')
  await page.click('#open-other')
  assert.equal(await page.locator('#open').getAttribute('aria-busy'), null)
  assert.equal(await page.locator('#open-other').getAttribute('aria-busy'), 'true', '等待换单要改用新入口')
  await evidence('01-preparing-no-mask')
  await page.evaluate(() => { window.dialogFixture.ready.value = true })
  await page.waitForTimeout(50)
  assert.equal(await page.locator('[data-app-modal-id]').getAttribute('data-dialog-phase'), 'preparing', '历史屏障未完成不能展开')
  await page.evaluate(() => { window.dialogFixture.history.value = false })
  await page.waitForSelector('[data-dialog-phase="open"]')
  assert.equal(await page.locator('.n-modal-mask:visible').count(), 1)
  assert.equal(await page.evaluate(() => document.querySelector('[data-app-modal-id]').contains(document.activeElement)), true, '正式展开时焦点必须进入弹窗')
  assert.equal(await page.evaluate(() => window.historyMounts), 1, '准备到展开不能重新挂载历史组件')
  assert.ok((await page.locator('.record').textContent()).includes('Original complete record'))
  assert.equal(await page.evaluate(() => window.dialogFrames.some(frame => !frame.text.includes('Original complete record'))), false, '可见首帧已有完整正文')
  await evidence('02-complete-open')
  // 同一次 Vue 更新中清空正文并关闭，真实节点变化不能影响离场画面。
  await page.locator('.scroll').evaluate(el => { el.scrollTop = 97 })
  const controlsBeforeClose = await page.locator('.fixture-content').evaluate(el => [...el.querySelectorAll('input,textarea,button')].map(control => {
    const style = getComputedStyle(control)
    return { disabled: control.disabled, color: style.color, background: style.backgroundColor, opacity: style.opacity }
  }))
  const cssBeforeClose = await page.locator('.css-evidence').evaluate(el=>({opacity:+getComputedStyle(el).opacity,line:parseFloat(getComputedStyle(el,'::before').width)}))
  await page.evaluate(async () => { window.dialogFixture.row.value = ''; window.dialogFixture.show.value = false; await window.dialogFixture.nextTick() })
  const leaving = page.locator('[data-dialog-exit-frame]')
  assert.ok((await leaving.textContent()).includes('Original complete record'))
  assert.equal(await leaving.locator('[id],[name]').count(), 0)
  const copiedControls = await leaving.evaluate(el => {
    const controls = [...el.querySelectorAll('.fixture-content input,.fixture-content textarea,.fixture-content button')]
    controls[0].focus()
    return { inert: el.inert, hidden: el.getAttribute('aria-hidden'), focused: el.contains(document.activeElement),
      controls: controls.map(control => { const style = getComputedStyle(control); return { disabled: control.disabled, color: style.color, background: style.backgroundColor, opacity: style.opacity } }) }
  })
  assert.equal(copiedControls.inert, true)
  assert.equal(copiedControls.hidden, 'true')
  assert.equal(copiedControls.focused, false, '副本即使主动调用 focus 也不能夺取焦点')
  assert.deepEqual(copiedControls.controls, controlsBeforeClose, '离场副本保留控件样式，不能因强制禁用产生灰色闪帧')
  assert.equal(await leaving.locator('.scroll').evaluate(el => el.scrollTop), 97)
  const cssCopied = await leaving.locator('.css-evidence').evaluate(el=>({opacity:+getComputedStyle(el).opacity,line:parseFloat(getComputedStyle(el,'::before').width),states:el.getAnimations({subtree:true}).map(a=>a.playState),animations:el.getAnimations({subtree:true}).map(a=>({name:a.animationName,time:a.currentTime,pseudo:a.effect?.pseudoElement,target:a.effect?.target===el,tag:a.effect?.target?.constructor.name}))}))
  assert.ok(Math.abs(cssCopied.opacity-cssBeforeClose.opacity)<.1, '副本不能重启正文延迟动画')
  assert.ok(Math.abs(cssCopied.line-cssBeforeClose.line)<12, '副本必须保留伪元素连接线进度')
  assert.ok(cssCopied.states.every(state=>state==='paused'), '旧画面的 CSS 动画必须暂停')
  if (evidenceDir) { await leaving.evaluate(el => { el.closest('.n-modal-container').getAnimations({ subtree: true }).filter(a=>!('animationName' in a)).forEach(a => a.pause()) }); await evidence('03-inert-close-frame'); await leaving.evaluate(el => { el.closest('.n-modal-container').getAnimations({ subtree: true }).filter(a=>!('animationName' in a)).forEach(a => a.play()) }) }
  // 回程中重新打开，从当前帧继续，并清理旧副本。
  await page.evaluate(() => { window.dialogFixture.row.value = 'Reopened record'; window.dialogFixture.show.value = true })
  await page.waitForSelector('[data-dialog-phase="open"]')
  assert.equal(await page.locator('[data-dialog-exit-frame]').count(), 0)
  assert.equal(await page.locator('.record').textContent(), 'Reopened record')
  // 换单请求先清空真实数据，但旧画面一直保留且无法交互。
  await page.evaluate(async () => { window.dialogFixture.ready.value = false; window.dialogFixture.row.value = ''; await window.dialogFixture.nextTick() })
  assert.ok((await page.locator('[data-dialog-exit-frame]').textContent()).includes('Reopened record'))
  await evidence('04-refresh-retains-record')
  await page.evaluate(async () => { window.dialogFixture.busy.value = true; await window.dialogFixture.nextTick() })
  assert.equal(await page.getByRole('button', { name: '取消等待并关闭' }).isDisabled(), true, '刷新期间写入仍禁止关闭')
  assert.ok((await page.locator('[data-dialog-exit-frame]').textContent()).includes('Reopened record'))
  await page.evaluate(async () => { window.dialogFixture.busy.value = false; await window.dialogFixture.nextTick() })
  await page.getByRole('button', { name: '取消等待并关闭' }).focus()
  assert.equal(await page.evaluate(() => document.activeElement.textContent), '取消等待并关闭', '刷新取消必须在原生焦点锁范围内')
  assert.equal(await page.getByRole('button', { name: '取消等待并关闭' }).evaluate(el=>el.closest('[inert]')), null, '取消按钮不能放在 inert 子树')
  await page.evaluate(() => { window.dialogFixture.row.value = 'Replacement complete record'; window.dialogFixture.ready.value = true })
  await page.waitForFunction(() => !document.querySelector('[data-dialog-exit-frame]'))
  assert.equal(await page.locator('.record').textContent(), 'Replacement complete record')
  // 写入失败不关闭时，移除只读画面并恢复唯一的实时草稿与焦点。
  await page.evaluate(async () => { window.dialogFixture.busy.value = true; await window.dialogFixture.nextTick() })
  assert.equal(await page.getByRole('status').filter({ hasText: '正在处理…' }).isVisible(), true)
  // 核验实际边界间距，防止提示仍贴着弹窗右边缘或落在窗口之外。
  const statusInset = await page.getByRole('status').filter({ hasText: '正在处理…' }).evaluate(el =>
    el.closest('[data-app-modal-id]').getBoundingClientRect().right - el.getBoundingClientRect().right)
  assert.ok(Math.abs(statusInset - 16) < 1, `处理提示应距弹窗右边框 16px，实际 ${statusInset}px`)
  assert.equal(await page.evaluate(() => document.activeElement.textContent), '正在处理…')
  await page.evaluate(() => { window.dialogFixture.busy.value = false })
  await page.waitForFunction(() => !document.querySelector('[data-dialog-exit-frame]'))
  assert.equal(await page.locator('.record').textContent(), 'Replacement complete record')
  assert.equal(await page.locator('.record').isVisible(), true, '失败后必须恢复实时草稿')
  // 成功提前清空草稿后仍在等待列表请求，整个等待期间都只能看到原画面。
  await page.evaluate(async () => { window.dialogFixture.busy.value = true; await window.dialogFixture.nextTick(); window.dialogFixture.row.value = ''; await window.dialogFixture.nextTick() })
  await page.waitForTimeout(350)
  assert.ok((await page.locator('[data-dialog-exit-frame]').textContent()).includes('Replacement complete record'), '保存后慢请求不能露出已重置的空表单')
  assert.equal(await page.locator('[data-dialog-exit-frame] .record').evaluate(el => {
    let opacity = 1
    for (let node = el; node instanceof HTMLElement; node = node.parentElement) opacity *= Number(getComputedStyle(node).opacity)
    return opacity
  }), 1, '保存画面的正文必须真实可见，不能冻结刷新淡入的透明首帧')
  assert.equal(await page.locator('[data-app-modal-id] .record').isVisible(), false)
  assert.equal(await page.getByRole('status').filter({ hasText: '正在处理…' }).isVisible(), true)
  await evidence('05-saving-retains-record')
  await page.keyboard.press('Escape')
  assert.equal(await page.evaluate(() => window.dialogFixture.show.value), true, '处理期间 Escape 不能关闭')
  await page.evaluate(async () => { window.dialogFixture.busy.value = false; await window.dialogFixture.nextTick(); window.dialogFixture.show.value = false; await window.dialogFixture.nextTick() })
  assert.ok((await page.locator('[data-dialog-exit-frame]').textContent()).includes('Replacement complete record'), '保存提前一帧清空后仍使用完整离场快照')
  await page.waitForFunction(() => !document.querySelector('[data-app-modal-id]'))
  await page.evaluate(() => { window.dialogFixture.row.value = 'After save'; window.dialogFixture.ready.value = true })
  await page.click('#open'); await page.waitForSelector('[data-dialog-phase="open"]')
  await page.click('#nested-trigger'); await page.waitForTimeout(60)
  const nestedCancel = page.getByRole('button', { name: '取消', exact: true })
  await nestedCancel.focus()
  assert.equal(await page.evaluate(() => document.activeElement.textContent), '取消', '父窗焦点锁必须允许访问子窗等待取消')
  await page.keyboard.press('Enter')
  await page.waitForFunction(() => !window.dialogFixture.nested.value)
  await page.evaluate(() => { window.dialogFixture.nestedReady.value = true })
  await page.click('#nested-trigger'); await page.waitForFunction(() => document.querySelectorAll('[data-dialog-phase="open"]').length === 2)
  await page.click('#close-nested'); await page.waitForFunction(() => document.querySelectorAll('[data-app-modal-id]').length === 1)
  assert.equal(await page.evaluate(() => document.activeElement.id), 'nested-trigger', '子窗口关闭恢复父窗入口焦点')
  // 父子共享写入状态时，父窗口真实入口隐藏，子窗口仍要回到父快照中对应的可见入口。
  await page.click('#nested-trigger'); await page.waitForFunction(() => document.querySelectorAll('[data-dialog-phase="open"]').length === 2)
  await page.evaluate(async () => {
    const original = Element.prototype.animate
    window.nestedLeavingMotion = null
    Element.prototype.animate = function (frames, options) {
      if (this.matches('[data-dialog-exit-frame]') && this.textContent.includes('Nested details')) window.nestedLeavingMotion = { frames, duration: options.duration }
      return original.call(this, frames, options)
    }
    window.restoreNestedAnimate = () => { Element.prototype.animate = original }
    window.dialogFixture.busy.value = true; await window.dialogFixture.nextTick()
    window.dialogFixture.busy.value = false; await window.dialogFixture.nextTick()
    window.dialogFixture.nested.value = false; await window.dialogFixture.nextTick()
  })
  const nestedMotion = await page.evaluate(() => window.nestedLeavingMotion)
  assert.equal(nestedMotion.duration, 280, '父只读画面仍可见时子窗口保留完整回程')
  assert.match(nestedMotion.frames.at(-1).transform, /translate.*scale/, '回程目标使用对应可见副本的位置')
  await page.waitForFunction(() => document.querySelectorAll('[data-app-modal-id]').length === 1)
  assert.equal(await page.evaluate(() => document.activeElement.id), 'nested-trigger')
  await page.evaluate(() => window.restoreNestedAnimate())
  await page.evaluate(() => window.dialogFixture.invalidate())
  await page.waitForFunction(() => !document.querySelector('[data-app-modal-id]'))
  assert.equal(await page.locator('[data-dialog-exit-frame]').count(), 0, '安全失效不留下旧数据离场画面')
  // 准备失败必须退出，没有孤立遮罩；取消后迟到就绪不能恢复窗口。
  await page.evaluate(() => { window.dialogFixture.show.value = false; window.dialogFixture.ready.value = false; window.dialogFixture.error.value = '' })
  await page.click('#open'); await page.waitForTimeout(30)
  await page.evaluate(() => { window.dialogFixture.error.value = 'Expected read failure' })
  await page.waitForFunction(() => !document.querySelector('[data-app-modal-id]'))
  assert.equal(await page.locator('.n-modal-mask:visible').count(), 0)
  await page.evaluate(() => { window.dialogFixture.error.value = '' })
  const leavesBeforeCancel = await page.evaluate(() => window.afterLeaves)
  await page.click('#open'); await page.getByRole('button', { name: '取消', exact: true }).click()
  assert.equal(await page.evaluate(() => window.afterLeaves), leavesBeforeCancel + 1, '取消准备也必须报告离场结束')
  await page.evaluate(() => { window.dialogFixture.ready.value = true })
  await page.waitForTimeout(80)
  assert.equal(await page.locator('[data-app-modal-id]').count(), 0)
  // 关闭中由另一入口重开慢请求，清理 A 不能删掉 B 的新来源。
  await page.evaluate(() => { window.dialogFixture.row.value = 'Origin A'; window.dialogFixture.ready.value = true })
  await page.click('#open'); await page.waitForSelector('[data-dialog-phase="open"]')
  await page.evaluate(async () => { window.dialogFixture.show.value = false; await window.dialogFixture.nextTick(); window.dialogFixture.ready.value = false; document.querySelector('#open-other').click(); await window.dialogFixture.nextTick() })
  await page.waitForSelector('[data-dialog-phase="preparing"]', { state: 'attached' })
  assert.equal(await page.locator('#open-other').getAttribute('aria-busy'), 'true', '慢请求重开必须保留 B 来源')
  assert.equal(await page.locator('.n-modal-mask:visible').count(), 0)
  await page.evaluate(() => { window.dialogFixture.row.value = 'Origin B'; window.dialogFixture.ready.value = true })
  await page.waitForSelector('[data-dialog-phase="open"]')
  await page.keyboard.press('Escape'); await page.waitForFunction(() => !document.querySelector('[data-app-modal-id]'))
  assert.equal(await page.evaluate(() => document.activeElement.id), 'open-other', '关闭中更换来源后焦点返回 B')
  // 显式换单来源变化可以发生在 show 始终为 true 时，不能被旧来源覆盖。
  await page.evaluate(() => { window.dialogFixture.row.value = 'Already open source A' })
  await page.click('#open'); await page.waitForSelector('[data-dialog-phase="open"]')
  await page.evaluate(() => { document.querySelector('#open-other').click(); window.dialogFixture.row.value = 'Already open source B' })
  await page.keyboard.press('Escape'); await page.waitForFunction(() => !document.querySelector('[data-app-modal-id]'))
  assert.equal(await page.evaluate(() => document.activeElement.id), 'open-other', '已打开换单仍接受新的显式来源')
  // 入场中开始写入或读取时，保留画面必须沿原时间轴展开到完整尺寸，而非冻结在某个缩小帧。
  for (const mode of ['busy', 'pending']) {
    await page.evaluate(mode => { window.dialogFixture.row.value = 'Opening ' + mode; window.dialogFixture.ready.value = true }, mode)
    await page.click('#open')
    await page.waitForFunction(() => {
      const el = document.querySelector('[data-dialog-phase="opening"]')
      return el && Number(getComputedStyle(el).opacity) > 0.05 && Number(getComputedStyle(el).opacity) < 0.9
    })
    await page.evaluate(async mode => {
      if (mode === 'busy') window.dialogFixture.busy.value = true
      else window.dialogFixture.ready.value = false
      await window.dialogFixture.nextTick()
      window.dialogFixture.row.value = ''; await window.dialogFixture.nextTick()
    }, mode)
    await page.waitForFunction(() => {
      const frame = document.querySelector('[data-dialog-exit-frame]')
      return document.querySelector('[data-dialog-phase="open"]') && frame && Math.abs(frame.getBoundingClientRect().width - 600) < 1 && Number(getComputedStyle(frame).opacity) === 1
    })
    const retained = await page.locator('[data-dialog-exit-frame]').evaluate(el => {
      const box = el.getBoundingClientRect()
      return { left: box.left, top: box.top, width: box.width, opacity: [...el.children].map(child => getComputedStyle(child).opacity) }
    })
    assert.ok(retained.opacity.every(opacity => opacity === '1'), mode + '入场接管后正文也必须完成淡入')
    assert.equal(await page.locator('[data-app-modal-id]').evaluate(el => getComputedStyle(el).visibility), 'hidden', '入场完成回调不能提前露出真实空正文')
    await page.waitForTimeout(120)
    if (mode === 'busy') await evidence('06-opening-save-completes')
    await page.evaluate(mode => {
      window.dialogFixture.row.value = 'Restored ' + mode
      if (mode === 'busy') window.dialogFixture.busy.value = false
      else window.dialogFixture.ready.value = true
    }, mode)
    await page.waitForFunction(() => !document.querySelector('[data-dialog-exit-frame]'))
    const restored = await page.locator('[data-app-modal-id]').boundingBox()
    assert.ok(Math.abs(restored.width - retained.width) < 1 && Math.abs(restored.x - retained.left) < 1 && Math.abs(restored.y - retained.top) < 1, mode + '恢复实时内容时不能跳尺寸或位置')
    await page.keyboard.press('Escape'); await page.waitForFunction(() => !document.querySelector('[data-app-modal-id]'))
  }
  // 入场快照接管后立即关闭并反向，回程首帧沿当前尺寸继续，旧入场回调不能覆盖新方向。
  await page.evaluate(() => { window.dialogFixture.row.value = 'Opening reverse' })
  await page.click('#open')
  await page.waitForFunction(() => {
    const el = document.querySelector('[data-dialog-phase="opening"]')
    return el && Number(getComputedStyle(el).opacity) > 0.05 && Number(getComputedStyle(el).opacity) < 0.9
  })
  const reverseFrames = await page.evaluate(async () => {
    const f = window.dialogFixture
    f.ready.value = false; await f.nextTick()
    const before = document.querySelector('[data-app-modal-id]').getBoundingClientRect().width
    f.show.value = false; await f.nextTick()
    const after = document.querySelector('[data-dialog-exit-frame]').getBoundingClientRect().width
    f.ready.value = true; f.row.value = 'Reversed complete'; f.show.value = true; await f.nextTick()
    return { before, after }
  })
  assert.ok(Math.abs(reverseFrames.before - reverseFrames.after) < 2, '入场等待中关闭不能跳到完整尺寸或过时快照')
  await page.waitForSelector('[data-dialog-phase="open"]')
  assert.equal(await page.locator('[data-dialog-exit-frame]').count(), 0)
  assert.equal(await page.locator('.record').textContent(), 'Reversed complete')
  assert.ok(Math.abs((await page.locator('[data-app-modal-id]').boundingBox()).width - 600) < 1)
  await page.keyboard.press('Escape'); await page.waitForFunction(() => !document.querySelector('[data-app-modal-id]'))
  // 通过真实媒体查询触发减少动态效果，记录实际 WAAPI 参数而非仅验证工具函数。
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.evaluate(() => {
    window.reducedDialogAnimations = []
    window.originalDialogAnimate = Element.prototype.animate
    Element.prototype.animate = function (frames, options) {
      if (this.matches('[data-app-modal-id], [data-dialog-exit-frame]')) {
        window.reducedDialogAnimations.push({ kind: this.hasAttribute('data-dialog-exit-frame') ? 'leave' : 'enter', frames, duration: typeof options === 'number' ? options : options?.duration })
      }
      return window.originalDialogAnimate.call(this, frames, options)
    }
    window.dialogFixture.row.value = 'Reduced motion record'
    window.dialogFixture.ready.value = true
  })
  assert.equal(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches), true)
  await page.click('#open-other'); await page.waitForSelector('[data-dialog-phase="open"]')
  await page.keyboard.press('Escape'); await page.waitForFunction(() => !document.querySelector('[data-app-modal-id]'))
  const reducedAnimations = await page.evaluate(() => window.reducedDialogAnimations)
  for (const kind of ['enter', 'leave']) {
    const animation = reducedAnimations.find(animation => animation.kind === kind)
    assert.ok(animation, '减少动态效果时仍完成 ' + kind + ' 生命周期')
    assert.equal(animation.duration, 80, '减少动态效果使用 80ms 淡入淡出')
    assert.ok(animation.frames.every(frame => frame.transform === 'none'), '减少动态效果不能包含位移或缩放')
    assert.deepEqual(animation.frames.map(frame => frame.opacity), kind === 'enter' ? ['0', '1'] : ['1', '0'])
  }
  assert.equal(await page.evaluate(() => document.activeElement.id), 'open-other', '减少动态效果关闭后仍返回真实入口焦点')
  await page.evaluate(() => { Element.prototype.animate = window.originalDialogAnimate })
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  assert.deepEqual(errors, [])
  console.log('PASS ' + (electronMode ? 'isolated Electron' : 'Chromium') + ': preparation barrier, complete first frame, unchanged inert snapshot styling, scroll/form isolation, reversal, refresh replacement, opening-to-busy/pending continuation, busy reset retention, nested shared-busy return and focus, explicit source replacement, invalidation, failure, cancellation, reduced-motion 80ms fade and focus.')
} finally { await browser?.close(); await electron?.close(); await server.close(); if (electronDirectory) await rm(electronDirectory, { recursive: true, force: true }) }
