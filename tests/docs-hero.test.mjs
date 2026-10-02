import assert from 'node:assert/strict'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import { mountHeroEntrance, pageEntryScript } from '../docs/site/hero-entrance.mjs'

// 以浏览器动画状态驱动测试，验证控制交接和有限请求帧，不复刻 CSS 插值算法。
function fixture(options = {}) {
  const hero = new EventTarget(), doc = new EventTarget(), win = new EventTarget(), reduced = new EventTarget()
  const frames = new Map()
  let id = 0, notifications = 0
  hero.dataset = {}
  hero.animations = [{ animationName: 'hero-enter-satellite', playState: 'running' }]
  hero.getAnimations = () => hero.animations
  doc.querySelector = () => options.absent ? null : hero
  doc.hidden = Boolean(options.hidden)
  doc.documentElement = { dataset: {} }
  doc.readyState = options.complete ? 'complete' : 'loading'
  reduced.matches = Boolean(options.reduced)
  win.matchMedia = () => reduced
  win.Event = Event
  win.scrollY = options.scrollY || 0
  win.location = { hash: options.hash || '' }
  win.requestAnimationFrame = fn => { frames.set(++id, fn); return id }
  win.cancelAnimationFrame = key => frames.delete(key)
  win.addEventListener('hero:entrance-frame', () => notifications++)
  return { hero, doc, win, reduced, frames, notifications: () => notifications,
    tick() { const pending = [...frames.values()]; frames.clear(); pending.forEach(fn => fn()) } }
}

test('head 启动脚本在首帧前选定出场或静态，锚点及减少动态不先播放动画', () => {
  for (const options of [{}, { hash: '#product-preview' }, { reduced: true }, { hidden: true }, { scrollY: 80 }]) {
    const f = fixture(options)
    // 执行实际嵌入 HTML 的脚本，验证序列化函数没有遗漏运行依赖。
    runInNewContext(pageEntryScript, { document: f.doc, window: f.win })
    assert.equal(f.doc.documentElement.dataset.heroEntrance, Object.keys(options).length ? 'static' : 'intro')
    assert.equal(f.doc.documentElement.dataset.navigationReady, undefined)
    assert.equal(f.frames.size, 0)
  }
})

test('首次定位期间保持即时滚动，load 后两帧才启用后续平滑导航', () => {
  for (const complete of [false, true]) {
    const f = fixture({ complete })
    runInNewContext(pageEntryScript, { document: f.doc, window: f.win })
    if (!complete) {
      assert.equal(f.frames.size, 0)
      f.win.dispatchEvent(new Event('load'))
    }
    f.tick()
    assert.equal(f.doc.documentElement.dataset.navigationReady, undefined)
    f.tick()
    assert.equal(f.doc.documentElement.dataset.navigationReady, 'true')
    assert.equal(f.frames.size, 0)
    f.win.dispatchEvent(new Event('load'))
    assert.equal(f.frames.size, 0)
  }
})

test('后续模块保留 head 选定的静态状态，不因锚点改变重新出场', () => {
  const f = fixture({ hash: '#product-preview' })
  runInNewContext(pageEntryScript, { document: f.doc, window: f.win })
  f.win.location.hash = ''
  mountHeroEntrance(f.doc, f.win)
  assert.equal(f.hero.dataset.heroSettled, 'true')
  assert.equal(f.frames.size, 0)
})

test('首屏仅在出场期间通知轨道，结束后取消帧且滚动不会重播', () => {
  const f = fixture(), destroy = mountHeroEntrance(f.doc, f.win)
  f.tick()
  assert.equal(f.notifications(), 1)
  assert.equal(f.frames.size, 1)
  f.hero.animations[0].playState = 'finished'
  f.tick()
  assert.equal(f.hero.dataset.heroSettled, 'true')
  assert.equal(f.frames.size, 0)
  const count = f.notifications()
  f.win.dispatchEvent(new Event('scroll'))
  destroy()
  assert.equal(f.notifications(), count)
})

test('滚动、触摸、按钮操作、键盘焦点和窗口变化立即交还最终状态', () => {
  for (const name of ['scroll', 'wheel', 'touchstart', 'pointerdown', 'resize', 'hashchange', 'pagehide', 'focusin']) {
    const f = fixture()
    mountHeroEntrance(f.doc, f.win)
    ;(name === 'focusin' ? f.hero : f.win).dispatchEvent(new Event(name))
    assert.equal(f.hero.dataset.heroSettled, 'true', name)
    assert.equal(f.frames.size, 0, name)
  }
})

test('减少动态、后台、锚点和恢复位置跳过出场；偏好变化与卸载释放帧', () => {
  for (const options of [{ reduced: true }, { hidden: true }, { hash: '#product-preview' }, { scrollY: 80 }]) {
    const f = fixture(options)
    mountHeroEntrance(f.doc, f.win)
    assert.equal(f.hero.dataset.heroSettled, 'true')
    assert.equal(f.frames.size, 0)
  }
  for (const mode of ['preference', 'visibility', 'destroy']) {
    const f = fixture(), destroy = mountHeroEntrance(f.doc, f.win)
    if (mode === 'preference') f.reduced.dispatchEvent(new Event('change'))
    if (mode === 'visibility') f.doc.dispatchEvent(new Event('visibilitychange'))
    if (mode === 'destroy') destroy()
    assert.equal(f.frames.size, 0)
    assert.equal(f.hero.dataset.heroSettled, 'true')
  }
})

test('无动画支持、无首屏及脚本晚到不会导致内容持续隐藏', () => {
  const absent = fixture({ absent: true })
  mountHeroEntrance(absent.doc, absent.win)()
  assert.equal(absent.frames.size, 0)
  const legacy = fixture()
  delete legacy.hero.getAnimations
  mountHeroEntrance(legacy.doc, legacy.win)
  assert.equal(legacy.hero.dataset.heroSettled, 'true')
  const late = fixture()
  late.hero.animations = []
  mountHeroEntrance(late.doc, late.win)
  late.tick()
  assert.equal(late.frames.size, 0)
})
