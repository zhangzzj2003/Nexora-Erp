import assert from 'node:assert/strict'
import { test } from 'node:test'
import { coverGuideAt, mountCover } from '../docs/site/cover-motion.mjs'
import { pointOnPath } from '../docs/site/webgl-stage.mjs'

const input = { origin: [750, 650], entry: [750, 1300], coverProgress: 0, width: 1500, height: 1045 }

test('封面引导线从按钮下方沿弧长伸向入库顶边，倒滚与直接跳滚结果确定', () => {
  let last = 0
  for (const progress of [0, .1, .2, .4, .6, .8, 1]) {
    const frame = coverGuideAt({ ...input, coverProgress: progress })
    assert.ok(frame.amount >= last && frame.amount <= 1)
    assert.deepEqual(frame.points[0], input.origin)
    assert.deepEqual(frame.points.at(-1), input.entry)
    assert.ok(frame.points.every(point => point.every(Number.isFinite)))
    last = frame.amount
  }
  const completed = coverGuideAt({ ...input, coverProgress: 1 })
  assert.deepEqual(pointOnPath(completed.points, completed.amount), input.entry)
  assert.deepEqual(coverGuideAt({ ...input, coverProgress: .2 }), coverGuideAt({ ...input, coverProgress: .2 }))
  assert.equal(coverGuideAt({ ...input, coverProgress: -1 }).amount, .065)
})

test('封面/舞台统一坐标，滚动平移不改变路径形状或端点，不追逐已退场窗口', () => {
  const before = coverGuideAt({ ...input, coverProgress: .5 })
  const translated = coverGuideAt({ ...input, origin: [750, -150], entry: [750, 500], coverProgress: .5 })
  before.points.forEach((point, index) => {
    assert.ok(Math.abs(translated.points[index][0] - point[0]) < 1e-9)
    assert.ok(Math.abs(translated.points[index][1] - (point[1] - 800)) < 1e-9)
  })
  assert.equal(coverGuideAt({ ...input, sceneProgress: .22 }), null)
  assert.ok(coverGuideAt({ ...input, sceneProgress: .15 }).alpha < 1)
  for (const change of [{ manual: true }, { staticMode: true }, { entry: [750, -30] }, { entry: [750, 500] }, { origin: [NaN, 0] }, { width: 0 }]) {
    assert.equal(coverGuideAt({ ...input, ...change }), null)
  }
})

test('快速跳出舞台清除固定路径，后台停帧，减少动态和卸载恢复原生入口', () => {
  // 模拟 DOM/可见性边界，验证真实控制器的离场清理，GPU 失败使用 SVG。
  const element = () => {
    const attrs = new Map(), values = new Set()
    return Object.assign(new EventTarget(), { hidden: false, style: { setProperty(name, value) { this[name] = value }, removeProperty(name) { delete this[name] } },
      classList: { toggle: (name, value) => value ? values.add(name) : values.delete(name), remove: name => values.delete(name), contains: name => values.has(name) },
      setAttribute: (name, value) => attrs.set(name, value), removeAttribute: name => attrs.delete(name), getAttribute: name => attrs.get(name) })
  }
  const doc = element(), win = element(), hero = element(), scene = element(), content = element(), origin = element(), host = element(), hint = element(), svg = element(), path = element(), tip = element(), board = element()
  const media = new Map(), frames = new Map(), canvases = []
  let sequence = 0
  win.innerWidth = 1500; win.innerHeight = 1045; win.scrollX = 0; win.scrollY = 0; win.devicePixelRatio = 1
  win.requestAnimationFrame = callback => { frames.set(++sequence, callback); return sequence }
  win.cancelAnimationFrame = id => frames.delete(id)
  win.matchMedia = query => { const value = element(); value.matches = false; media.set(query, value); return value }
  hero.getBoundingClientRect = () => ({ top: -win.scrollY, bottom: 1045 - win.scrollY, height: 1045 })
  scene.getBoundingClientRect = () => ({ top: 1045 - win.scrollY, bottom: 4600 - win.scrollY })
  origin.getBoundingClientRect = () => ({ left: 748, top: 740 - win.scrollY, width: 4, height: 4 })
  board.getBoundingClientRect = () => ({ left: 30, top: 1300 - win.scrollY, width: 1440, height: 650 })
  hero.querySelector = selector => ({ '.cover-content': content, '.guide-origin': origin, '.cover-guide': host, '.cover-scroll': hint })[selector]
  scene.querySelector = selector => selector === '.scene-board' ? board : { getBoundingClientRect: () => ({ left: 30, right: 1470, top: 1350 - win.scrollY }) }
  host.ownerDocument = doc; host.querySelector = () => svg; host.append = canvas => canvases.push(canvas)
  svg.querySelector = selector => selector === 'path' ? path : tip
  doc.querySelector = selector => ({ '[data-cover]': hero, '.scroll-scene': scene, '.site-header': { offsetHeight: 80 } })[selector]
  doc.createElement = () => { const canvas = element(); canvas.getContext = () => null; canvas.remove = () => { canvas.removed = true }; return canvas }
  const flush = () => { const pending = [...frames.values()]; frames.clear(); pending.forEach(callback => callback()) }
  const destroy = mountCover(doc, win)
  flush()
  assert.equal(host.hidden, false)
  assert.ok(path.getAttribute('d'))
  win.scrollY = 6000; win.dispatchEvent(new Event('scroll')); flush()
  assert.equal(host.hidden, true); assert.equal(path.getAttribute('d'), undefined)
  assert.equal(frames.size, 0)
  doc.hidden = true; win.scrollY = 0; win.dispatchEvent(new Event('scroll'))
  assert.equal(frames.size, 0)
  doc.hidden = false; doc.dispatchEvent(new Event('visibilitychange')); flush()
  assert.equal(host.hidden, false)
  const reduced = media.get('(prefers-reduced-motion: reduce)')
  reduced.matches = true; reduced.dispatchEvent(new Event('change')); flush()
  assert.equal(host.hidden, true); assert.equal(hero.classList.contains('cover-motion'), false)
  assert.equal(hint.inert, false)
  destroy()
  assert.ok(canvases.every(canvas => canvas.removed))
  assert.equal(content.style['--cover-y'], undefined)
  win.dispatchEvent(new Event('scroll')); assert.equal(frames.size, 0)
  // 截图区插在封面和舞台之间时，引导线只到截图入口，不能跨越所有图片。
  const query = doc.querySelector
  doc.querySelector = selector => selector === '#product-preview' ? { getBoundingClientRect: () => ({ left: 30, width: 1440, top: 1045 - win.scrollY }) } : query(selector)
  win.scrollY = 1045
  const destroyPreview = mountCover(doc, win)
  flush()
  assert.match(path.getAttribute('d'), /L 750 24$/)
  win.scrollY = 2000; win.dispatchEvent(new Event('scroll')); flush()
  assert.equal(host.hidden, true)
  destroyPreview()
})
