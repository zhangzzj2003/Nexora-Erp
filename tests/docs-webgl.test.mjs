import { pageOrbitSegments, orbitProgress, orbitCardPose, orbitRing, finaleGeometry, finaleOrbit, mountPageOrbit } from '../docs/site/product-orbit.mjs'
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { cubicPoints, trimPath, pointOnPath, ribbonMesh, floorLightAt, createWebGLStage, createWebGLGuide } from '../docs/site/webgl-stage.mjs'
import { sceneAt, mountScene } from '../docs/site/motion.mjs'
import { focusLayout, windowGeometry, interpolateWindowPose, connectionEndpoints, projectWindowPoint, sceneBoardHeight, advanceMotionClock } from '../docs/site/scene-geometry.mjs'

test('GPU 路径按实际弧长裁切，端点、倒滚和零长度输入保持稳定', () => {
  const path = cubicPoints([0, 0], [20, 50], [80, 50], [100, 0])
  assert.deepEqual(path[0], [0, 0]); assert.deepEqual(path.at(-1), [100, 0])
  assert.deepEqual(pointOnPath(path, 0), [0, 0]); assert.deepEqual(pointOnPath(path, 1), [100, 0])
  assert.deepEqual(pointOnPath([[0, 0], [10, 0], [10, 90]], .5), [10, 40])
  assert.deepEqual(trimPath(path, -1), trimPath(path, 0))
  assert.deepEqual(trimPath(path, 2), trimPath(path, 1))
  const mesh = ribbonMesh(path, 2)
  assert.ok(mesh.length > 0); assert.ok([...mesh].every(Number.isFinite))
  assert.equal(ribbonMesh([[0, 0], [0, 0]], 2).length, 0)
})

// 生命周期测试模拟 GPU 边界，真实着色器编译与图像对齐另由浏览器验收。
function fixture({ unavailable = false, compileFailure = false } = {}) {
  const counters = { contexts: 0, draws: 0, shaders: 0, programs: 0, buffers: 0, frames: 0, materials: [], colors: [], progress: [] }
  const classes = new Set(), canvases = []
  const scene = { dataset: {}, classList: { toggle: (name, on) => on ? classes.add(name) : classes.delete(name) } }
  const makeGL = () => {
    const gl = {
      lost: false, createShader: () => { counters.shaders++; return {} }, deleteShader: () => counters.shaders--,
      createProgram: () => { counters.programs++; return {} }, deleteProgram: () => counters.programs--,
      createBuffer: () => { counters.buffers++; return {} }, deleteBuffer: () => counters.buffers--,
      getShaderParameter: () => !compileFailure, getShaderInfoLog: () => 'Unsupported shader', getProgramParameter: () => true,
      getAttribLocation: () => 0, getUniformLocation: (_, name) => name, getParameter: () => 4096,
      isContextLost: () => gl.lost, drawArrays: () => counters.draws++
    }
    for (const method of ['shaderSource', 'compileShader', 'attachShader', 'linkProgram', 'enable', 'blendFuncSeparate', 'useProgram', 'bindBuffer', 'bufferData', 'enableVertexAttribArray', 'vertexAttribPointer', 'uniform1f', 'uniform2f', 'uniform3f', 'uniform4f', 'viewport', 'clearColor', 'clear']) gl[method] = () => {}
    gl.uniform1f = (uniform, value) => { if (uniform === 'u_kind') counters.materials.push(value); if (uniform === 'u_progress') counters.progress.push(value) }
    gl.uniform4f = (uniform, ...value) => { if (uniform === 'u_color') counters.colors.push(value) }
    return gl
  }
  const doc = { createElement() {
    const listeners = new Map(), gl = makeGL()
    const canvas = { style: {}, gl, hidden: false, width: 300, height: 150, setAttribute() {},
      getContext() { counters.contexts++; return unavailable ? null : gl },
      addEventListener: (name, handler) => listeners.set(name, handler), removeEventListener: name => listeners.delete(name),
      fire: name => listeners.get(name)?.({ preventDefault() {} }), remove() { canvas.removed = true }
    }
    return canvas
  } }
  const board = { ownerDocument: doc, closest: () => scene, append: canvas => canvases.push(canvas) }
  const guideHost = { ...board, classList: scene.classList }
  return { counters, canvases, scene, doc, guideHost, create: () => createWebGLStage(board, () => counters.frames++), createGuide: () => createWebGLGuide(guideHost, () => counters.frames++) }
}
const frame = () => ({ width: 1200, height: 600, layout: sceneAt(.8).windows, progress: .8, ratio: 3, staticMode: false,
  connections: [{ visible: true, points: [[0, 0], [100, 100]], amount: .5, node: .3 }] })

test('静态场景不创建 GPU；桌面按需渲染并限制像素密度，销毁释放资源', () => {
  const f = fixture(), stage = f.create()
  assert.equal(stage.draw({ ...frame(), staticMode: true }), false)
  assert.equal(f.counters.contexts, 0)
  assert.equal(stage.draw(frame()), true)
  assert.equal(f.scene.dataset.renderer, 'webgl')
  assert.equal(f.canvases[0].width, 2560)
  assert.ok(f.counters.draws > 0)
  const draws = f.counters.draws
  stage.draw({ ...frame(), staticMode: true })
  assert.equal(f.counters.draws, draws)
  assert.equal(f.scene.dataset.renderer, 'fallback')
  stage.destroy()
  assert.equal(f.counters.shaders, 0); assert.equal(f.counters.programs, 0); assert.equal(f.counters.buffers, 0)
  assert.ok(f.canvases.every(c => c.removed))
  assert.equal(stage.draw(frame()), false)
})

test('WebGL 不可用或着色器失败时保留 HTML/SVG，不泄漏半初始化资源', () => {
  for (const option of [{ unavailable: true }, { compileFailure: true }]) {
    const f = fixture(option), stage = f.create()
    assert.equal(stage.draw(frame()), false)
    assert.equal(f.scene.dataset.renderer, 'fallback')
    assert.ok(f.canvases.every(c => c.hidden))
    stage.destroy()
    assert.equal(f.counters.shaders, 0); assert.equal(f.counters.programs, 0); assert.equal(f.counters.buffers, 0)
  }
})

test('GPU 上下文丢失即回退，恢复时重建资源并重绘最后业务画面', () => {
  const f = fixture(), stage = f.create()
  stage.draw(frame())
  f.canvases[0].gl.lost = true; f.canvases[0].fire('webglcontextlost')
  assert.equal(f.scene.dataset.renderer, 'fallback'); assert.equal(stage.draw(frame()), false)
  f.canvases[0].gl.lost = false; f.canvases[0].fire('webglcontextrestored')
  // 恢复只请求帧，由场景控制器检查页面可见性后才绘制。
  assert.equal(f.scene.dataset.renderer, 'fallback')
  stage.draw(frame())
  assert.equal(f.scene.dataset.renderer, 'webgl'); assert.equal(f.counters.frames, 2)
  stage.destroy()
  assert.equal(f.counters.programs, 0); assert.equal(f.counters.buffers, 0)
})

test('GPU 绘制漫射光池、低角度掠光和接触阴影，滚动控制光场且不绘制内容镜像', () => {
  const f = fixture(), stage = f.create()
  assert.equal(stage.draw(frame()), true)
  assert.ok(f.counters.materials.includes(3), '地面漫射光池')
  assert.ok(f.counters.materials.includes(4), '窗脚低角度掠光')
  assert.ok(f.counters.materials.includes(2), '保留接触阴影')
  assert.ok(!f.counters.materials.includes(0) && !f.counters.materials.includes(1), '不绘制金属镀层或假表格倒影')
  assert.ok(f.counters.progress.every(p => p === .8))
  stage.draw({ ...frame(), progress: .2 })
  assert.equal(f.counters.progress.at(-1), .2)
  assert.ok(f.counters.draws > f.counters.materials.length, '来源线仍由 GPU 绘制')
  stage.destroy()
})

test('窗口切换从当前实体姿态接续，改变画布与舞台高度也不跳起点或底线', () => {
  const width = 1440, fromHeight = 540, toHeight = 650
  const source = sceneAt(.92).windows.map(item => windowGeometry(item, width, fromHeight))
  const targets = focusLayout('stock').map(item => windowGeometry(item, width, toHeight))
  let last = source
  for (let n = 0; n <= 60; n++) {
    const q = n / 60, height = fromHeight + (toHeight - fromHeight) * q
    const poses = targets.map((item, i) => interpolateWindowPose(source[i], item, q, height))
    for (let i = 0; i < 3; i++) {
      assert.ok(Math.abs(poses[i].top + poses[i].pixelHeight - (height - 35)) < 1e-9)
      assert.ok(Math.abs(poses[i].pixelWidth - last[i].pixelWidth) < 20)
      assert.ok(Math.abs(poses[i].left - last[i].left) < 20)
      if (n === 0) for (const key of ['left', 'top', 'pixelWidth', 'pixelHeight', 'rotation', 'opacity']) assert.equal(poses[i][key], source[i][key])
    }
    last = poses
  }
  const interrupted = interpolateWindowPose(source[1], targets[1], .31, 574.1)
  const next = windowGeometry(focusLayout('finance')[1], width, toHeight)
  const restart = interpolateWindowPose(interrupted, next, 0, 574.1)
  for (const key of ['left', 'top', 'pixelWidth', 'pixelHeight', 'rotation', 'opacity']) assert.equal(restart[key], interrupted[key])
})

test('来源线拒绝退场、反向交叉与屏外端点，正常线路不形成回环', () => {
  const a = { right: [300, 200], left: [200, 200], opacity: 1 }
  const b = { left: [500, 300], right: [800, 300], opacity: 1 }
  assert.deepEqual(connectionEndpoints(a, b, 1440, 650), { start: [300, 200], end: [500, 300], bend: 90 })
  for (const pair of [[a, { ...b, opacity: .25 }], [{ ...a, right: [-10, 200] }, b], [b, a], [a, null], [a, { ...b, left: [310, 300] }]]) assert.equal(connectionEndpoints(...pair, 1440, 650), null)
  assert.ok(connectionEndpoints(b, { ...a, right: [300, 550] }, 1440, 650, true))
  const pose = windowGeometry(sceneAt(.92).windows[0], 1440, 540)
  const point = projectWindowPoint(pose, 550 * pose.scale, 230 * pose.scale)
  assert.ok(point.every(Number.isFinite))
})

test('GPU 来源淡出独立于路径行程，旧线清空后不遗留下一帧', () => {
  const f = fixture(), stage = f.create(), input = frame()
  stage.draw({ ...input, connections: [{ ...input.connections[0], alpha: .25 }] })
  assert.ok(Math.abs(f.counters.colors.at(-1)[3] - .95 * .5 * .25) < 1e-9)
  f.counters.colors = []
  stage.draw({ ...input, connections: [] })
  assert.equal(f.counters.colors.length, 0)
  stage.destroy()
})

test('灯光基于真实透视窗底，聚焦、倒滚和宽高变化后仍贴合；退场窗口不产生残留光池', () => {
  for (const [width, height] of [[1440, 540], [970, 650], [1280, 360]]) {
    for (const layout of [sceneAt(.45).windows, sceneAt(.92).windows, focusLayout('stock')]) for (const item of layout) {
      const pose = windowGeometry(item, width, height), light = floorLightAt(pose, width, height)
      if (!light) continue
      const left = projectWindowPoint(pose, 0, pose.pixelHeight), right = projectWindowPoint(pose, pose.pixelWidth, pose.pixelHeight)
      assert.ok(Math.abs(light.center - (left[0] + right[0]) / 2) < 1e-9)
      assert.ok(Math.abs(light.span - (right[0] - left[0])) < 1e-9)
      assert.ok(Math.abs(light.bottom - (height - 35)) < 1e-9)
      assert.ok(light.depth >= 85 && light.depth <= 128)
    }
  }
  assert.equal(floorLightAt({ ...sceneAt(.92).windows[0], opacity: 0 }, 1440, 540), null)
  assert.equal(floorLightAt({ ...sceneAt(.92).windows[0], x: -3 }, 1440, 540), null)
  assert.equal(floorLightAt({ ...sceneAt(.92).windows[0], rotation: NaN }, 1440, 540), null)
})

test('舞台离屏时切换低高度或减少动态偏好，也立即释放旧尺寸与键盘锁定', () => {
  for (const preference of ['(max-height: 619px)', '(prefers-reduced-motion: reduce)']) {
    const classes = () => {
      const values = new Set()
      return { add: (...names) => names.forEach(name => values.add(name)), remove: (...names) => names.forEach(name => values.delete(name)), toggle: (name, on) => on ? values.add(name) : values.delete(name), contains: name => values.has(name) }
    }
    const element = () => Object.assign(new EventTarget(), { style: { cssText: '' }, dataset: {}, classList: classes(), setAttribute(name, value) { this[name] = value }, removeAttribute(name) { delete this[name] }, querySelectorAll: () => [] })
    const doc = element(), win = element(), scene = element(), board = element(), status = element(), canvases = [], media = new Map()
    const windows = ['receipt', 'stock', 'finance'].map(() => {
      const el = element(), viewport = element()
      el.querySelector = () => viewport
      return el
    })
    doc.defaultView = win; doc.documentElement = { lang: 'zh-CN' }; doc.querySelector = () => scene
    scene.ownerDocument = doc; board.ownerDocument = doc; board.closest = () => scene
    board.append = canvas => canvases.push(canvas)
    board.querySelectorAll = () => []
    scene.getBoundingClientRect = () => ({ top: 2000, bottom: 4000 })
    scene.querySelector = selector => selector === '.scene-board' ? board : selector === '[data-demo-status]' ? status : windows[['receipt', 'stock', 'finance'].findIndex(key => selector.includes(`"${key}"`))]
    doc.createElement = () => { const canvas = element(); canvas.remove = () => { canvas.removed = true }; return canvas }
    win.innerHeight = 1045; win.CustomEvent = CustomEvent
    win.sessionStorage = { getItem: () => null, removeItem() {} }
    win.matchMedia = query => { const m = element(); m.matches = false; media.set(query, m); return m }
    win.IntersectionObserver = class { observe() {} disconnect() {} }
    win.requestAnimationFrame = () => { throw new Error('离屏舞台不应请求动画帧') }
    const destroy = mountScene(doc, win)
    windows.forEach(el => { el.style.cssText = 'width:800px;transform:rotateY(30deg)'; el.inert = true; el.setAttribute('aria-hidden', 'true'); el.classList.add('is-focused', 'is-compact') })
    board.style.height = '650px'
    const m = media.get(preference); m.matches = true; m.dispatchEvent(new Event('change'))
    assert.equal(scene.classList.contains('motion-enabled'), false)
    assert.equal(board.style.height, '')
    for (const el of windows) {
      assert.equal(el.style.cssText, ''); assert.equal(el.inert, false)
      assert.equal(el['aria-hidden'], undefined); assert.equal(el.classList.contains('is-compact'), false)
    }
    assert.ok(canvases.every(canvas => canvas.hidden))
    destroy()
    assert.ok(canvases.every(canvas => canvas.removed))
  }
})

test('最低动态视口按实际说明和按钮高度留空间，所有过渡阶段都容纳舞台', () => {
  for (const [width, height] of [[1280, 620], [1366, 768], [1015, 1039], [2560, 1440]]) {
    for (const chrome of [231, 260, 310]) for (const compact of [0, .25, .5, .75, 1]) {
      const board = sceneBoardHeight(width, height, chrome, compact)
      assert.ok(board + chrome + 8 <= height)
      assert.ok(board <= 650)
      const pose = windowGeometry(sceneAt(.92).windows[1], width, board)
      assert.ok(pose.top >= 0 && pose.pixelHeight <= board - 35)
    }
  }
})

test('慢帧和后台恢复不会跳过大段切换行程，正常帧保持实际时间', () => {
  let clock = advanceMotionClock({ elapsed: 0, lastTime: null }, 100)
  clock = advanceMotionClock(clock, 116)
  assert.equal(clock.elapsed, 16)
  clock = advanceMotionClock(clock, 370)
  assert.equal(clock.elapsed, 50)
  clock = advanceMotionClock({ ...clock, lastTime: null }, 90000)
  assert.equal(clock.elapsed, 50)
  clock = advanceMotionClock(clock, 90016)
  assert.equal(clock.elapsed, 66)
})

test('封面轻细引导线按需创建 GPU，空场景停绘，丢失/恢复与销毁不泄漏资源', () => {
  const f = fixture(), guide = f.createGuide()
  assert.equal(guide.draw({ ...frame(), connections: [] }), false)
  assert.equal(guide.draw({ ...frame(), staticMode: true }), false)
  assert.equal(f.counters.contexts, 0)
  assert.equal(guide.draw(frame()), true)
  assert.equal(f.canvases.length, 1)
  assert.equal(f.counters.contexts, 1)
  assert.ok(f.counters.colors.at(-1)[3] > .5, '初始短线仍然清晰，不再按长度降低透明度')
  const before = f.counters.draws
  guide.draw({ ...frame(), connections: [] })
  assert.equal(f.counters.draws, before)
  assert.equal(f.canvases[0].hidden, true)
  f.canvases[0].gl.lost = true; f.canvases[0].fire('webglcontextlost')
  assert.equal(guide.draw(frame()), false)
  f.canvases[0].gl.lost = false; f.canvases[0].fire('webglcontextrestored')
  assert.equal(guide.draw(frame()), true)
  guide.destroy()
  assert.equal(f.counters.programs, 0); assert.equal(f.counters.buffers, 0); assert.equal(f.counters.shaders, 0)
  assert.equal(f.canvases[0].removed, true)
})

test('封面 WebGL 初始化失败只保留 SVG，不影响业务舞台或泄漏半初始化资源', () => {
  for (const option of [{ unavailable: true }, { compileFailure: true }]) {
    const f = fixture(option), guide = f.createGuide()
    assert.equal(guide.draw(frame()), false)
    assert.ok(f.canvases[0].hidden)
    guide.destroy()
    assert.equal(f.counters.programs, 0); assert.equal(f.counters.buffers, 0); assert.equal(f.counters.shaders, 0)
  }
})

// 运行真实舞台控制器，DOM/GPU 只模拟边界；滚动位置与动画帧可以精确推进。
function scrollingScene({ real = false } = {}) {
  const element = () => {
    const attrs = new Map(), classes = new Set()
    return Object.assign(new EventTarget(), {
      dataset: {}, style: { setProperty(name, value) { this[name] = value } }, children: [],
      classList: { add: name => classes.add(name), remove: (...names) => names.forEach(name => classes.delete(name)), toggle: (name, yes) => yes ? classes.add(name) : classes.delete(name) },
      setAttribute: (name, value) => attrs.set(name, value), removeAttribute: name => attrs.delete(name), getAttribute: name => attrs.get(name),
      querySelectorAll: () => [], closest: () => null
    })
  }
  const doc = element(), win = element(), scene = element(), board = element(), svg = element(), sticky = element()
  const groups = [element(), element()], buttons = Array.from({ length: 4 }, element), captions = Array.from({ length: 4 }, element)
  const frames = new Map(), windows = ['receipt', 'stock', 'finance'].map(() => {
    const el = element(), pane = element(), heading = { focus() {} }
    el.querySelector = selector => selector === '[data-content]' ? pane : selector === 'h2' ? heading : null
    return el
  })
  let sequence = 0, latest
  win.innerHeight = 1045; win.scrollX = 0; win.scrollY = 1045 + .45 * 2508; win.CustomEvent = CustomEvent
  win.sessionStorage = { getItem: () => null, removeItem() {} }; win.devicePixelRatio = 1
  win.matchMedia = () => Object.assign(element(), { matches: false })
  win.IntersectionObserver = class { observe() {} disconnect() {} }
  win.getComputedStyle = () => ({ paddingTop: '0', paddingBottom: '0', marginTop: '0', marginBottom: '0' })
  win.requestAnimationFrame = fn => { frames.set(++sequence, fn); return sequence }; win.cancelAnimationFrame = id => frames.delete(id)
  win.scrollTo = options => { win.lastScroll = options; win.scrollY = options.top; win.dispatchEvent(new Event('scroll')) }
  doc.defaultView = win; doc.documentElement = { lang: 'zh-CN' }; doc.querySelector = () => scene
  doc.createElement = () => Object.assign(element(), { getContext: () => null, remove() {} })
  scene.dataset.surface = real ? 'screenshots' : 'sandbox'
  scene.ownerDocument = doc; board.ownerDocument = doc; board.parentElement = sticky; sticky.children = [board]
  board.clientWidth = 1200; board.closest = () => scene; board.append = () => {}
  Object.defineProperty(board, 'clientHeight', { get: () => parseFloat(board.style.height) || 540 })
  board.getBoundingClientRect = () => ({ left: 0, top: 100, width: 1200, height: board.clientHeight })
  board.querySelector = selector => selector === '.connection-layer' ? svg : null
  svg.querySelector = selector => groups[Number(selector.match(/\d+/)[0])]
  scene.getBoundingClientRect = () => ({ top: 1045 - win.scrollY, bottom: 4598 - win.scrollY, height: 3553 })
  // 收集真实组件的倍率，验证滚动、聚焦与停止绘制使用同一镜头时序。
  const realPanes = real ? ['receipt','stock','finance'].map(element) : []
  scene.querySelectorAll = selector => selector === '[data-stage]' ? buttons : selector === '[data-caption]' ? captions : selector === '.real-interface' ? realPanes : []
  scene.querySelector = selector => selector === '.scene-board' ? board : windows[['receipt', 'stock', 'finance'].findIndex(key => selector === `[data-window="${key}"]`)] ?? null
  scene.addEventListener('scene:geometry', event => { latest = event.detail })
  const destroy = mountScene(doc, win)
  const tick = time => { const pending = [...frames.values()]; frames.clear(); pending.forEach(fn => fn(time)) }
  const click = (selector, data) => {
    const event = new Event('click'); Object.defineProperty(event, 'target', { value: { closest: name => name === selector ? { dataset: data } : null } })
    scene.dispatchEvent(event)
  }
  const scroll = p => { win.scrollY = 1045 + p * 2508; win.dispatchEvent(new Event('scroll')) }
  tick(0)
  return { scene, win, doc, windows, board, buttons, realPanes, tick, click, scroll, destroy, latest: () => latest, queued: () => frames.size }
}

test('聚焦与编辑都不能锁住页面滚动，下一帧直接使用真实进度；快跳和倒滚不延迟恢复', () => {
  const f = scrollingScene()
  f.click('[data-focus]', { focus: 'finance' }); f.tick(16); f.tick(32)
  assert.equal(f.scene.dataset.mode, 'focus')
  // 编辑打断正在进行的放大，但后续滚动仍必须接管。
  const event = new Event('focusin')
  Object.defineProperty(event, 'target', { value: { closest: name => name === '.sandbox-content' ? {} : null, matches: () => true } })
  f.scene.dispatchEvent(event)
  for (const progress of [.7, .1, .95, .25]) {
    f.scroll(progress); f.tick(1000 + progress * 10)
    assert.equal(f.scene.dataset.mode, 'scroll')
    assert.ok(Math.abs(f.latest().progress - progress) < 1e-12)
    assert.equal(f.latest().manual, false)
    assert.equal(f.queued(), 0, '没有恢复补间或闲时循环')
    const expected = windowGeometry(sceneAt(progress).windows[0], 1200, f.board.clientHeight)
    assert.ok(Math.abs(parseFloat(f.windows[0].style.width) - expected.pixelWidth) < 1e-9)
  }
  f.doc.hidden = true; f.scroll(.6)
  assert.equal(f.queued(), 0)
  f.doc.hidden = false; f.doc.dispatchEvent(new Event('visibilitychange')); f.tick(99999)
  assert.ok(Math.abs(f.latest().progress - .6) < 1e-12)
  f.destroy()
})

test('分步和总览改变真实滚动位置，滚动条与所选阶段一致，没有独立暂停状态', () => {
  const f = scrollingScene()
  f.click('[data-focus]', { focus: 'receipt' }); f.tick(16)
  f.click('[data-stage]', { stage: '2' }); f.tick(32)
  assert.equal(f.win.lastScroll.top, 1045 + .8 * 2508)
  assert.equal(f.win.lastScroll.behavior, 'smooth')
  assert.equal(f.scene.dataset.mode, 'scroll')
  assert.equal(f.buttons[2].getAttribute('aria-pressed'), 'true')
  f.click('[data-overview]', {}); f.tick(48)
  assert.equal(f.win.lastScroll.top, 1045 + .92 * 2508)
  assert.ok(Math.abs(f.latest().progress - .92) < 1e-12)
  assert.equal(f.buttons[3].getAttribute('aria-pressed'), 'true')
  f.destroy()
})


// 全页轨道沿真实页面坐标接续；只裁掉整段离屏路径，不改变端点关系。
test('全页轨道保持节点顺序和滚动平移，拒绝无效或反向路径，椭圆闭合', () => {
  const nodes = [[100, -200], [900, 400], [120, 1000], [900, 2000]]
  const paths = pageOrbitSegments(nodes, 1440, 900)
  assert.equal(paths.length, 2)
  assert.deepEqual(paths[0].points[0], nodes[0])
  assert.deepEqual(paths[0].points.at(-1), nodes[1])
  const translated = pageOrbitSegments(nodes.map(([x,y]) => [x,y-40]), 1440, 900)
  paths.forEach((path,i) => path.points.forEach((point,k) => assert.ok(Math.abs(translated[i].points[k][1] - (point[1] - 40)) < 1e-8)))
  assert.equal(pageOrbitSegments([[0,100],[0,0]], 100, 100).length, 0)
  assert.equal(pageOrbitSegments([[NaN,0],[0,100]], 100, 100).length, 0)
  assert.equal(pageOrbitSegments(nodes, 0, 900).length, 0)
  // 手机正文高度区间只沿外缘走，仍接入真实编号端点。
  const mobilePath = pageOrbitSegments([[195,600],[40,1500]],390,844,true)[0].points
  assert.deepEqual(mobilePath[16],[12,632]); assert.deepEqual(mobilePath[17],[12,1476])
  assert.deepEqual(mobilePath.at(-1),[40,1500])
  const ring = orbitRing([720,450], [600,220], .6)
  assert.ok(Math.hypot(ring[0][0]-ring.at(-1)[0],ring[0][1]-ring.at(-1)[1]) < 1e-8)
  assert.ok(ring.flat().every(Number.isFinite))
})

function pageOrbitFixture(options = {}) {
  const f = fixture(options), frames = new Map(), media = [new EventTarget(),new EventTarget()]
  media.forEach(item => { item.matches = false })
  const win = Object.assign(new EventTarget(), { innerWidth: 1440, innerHeight: 900, devicePixelRatio: 3 })
  let sequence = 0, query = 0, top = 120, angle
  const styles = {}, stage = { offsetHeight: 7, dataset: { orbitNode: 'stage' }, getBoundingClientRect: () => ({left:100,top:Math.max(48,top+600),width:7,height:7}), closest: () => ({getBoundingClientRect:()=>({top:top+600})}) }
  win.requestAnimationFrame = fn => { frames.set(++sequence,fn); return sequence }
  win.cancelAnimationFrame = id => frames.delete(id)
  win.matchMedia = () => media[query++ % 2]
  const doc = Object.assign(new EventTarget(), f.doc, { hidden: false })
  const svg = { innerHTML:'',setAttribute() {} }
  const hero = { getBoundingClientRect: () => ({ top,bottom:top+900,height:900 }) }
  const node = { offsetHeight: 44, dataset: {}, getBoundingClientRect: () => ({left:100,top,width:44,height:44}) }
  const other = { ...node,getBoundingClientRect: () => ({left:900,top:top+600,width:44,height:44}) }
  const card = { dataset:{}, getBoundingClientRect: () => ({top,bottom:top+600,height:600}),style: {setProperty: (name,value) => { styles[name]=value; if(name==='--orbit-angle') angle=value },removeProperty(name) {delete styles[name]} } }
  const host = { ...f.guideHost,ownerDocument:doc,dataset:{},querySelector:()=>svg }
  const finale = options.finale ? { dataset: {}, getBoundingClientRect: () => ({top:top+2200,height:640}) } : null
  const endingRing = options.ending ? {getBoundingClientRect:()=>({left:150,top:top+2200+640*.24,width:1040,height:640*.52})} : null
  const endingNode = {offsetHeight:1,dataset:{orbitNode:'finale'},getBoundingClientRect:()=>({left:0,top:top+2200,width:1,height:1})}
  const downloadNode = {...node,dataset:{orbitNode:'edge'},getBoundingClientRect:()=>({left:110,top:top+2120,width:200,height:24})}
  doc.querySelector = selector => selector === '[data-finale-ring]' ? endingRing : selector === '.page-orbit' ? host : selector === '[data-cover]' ? hero : selector === '[data-orbit-finale]' ? finale : null
  doc.querySelectorAll = selector => selector === '[data-orbit-node]' ? [node,options.sticky ? stage : other,...(options.ending?[downloadNode,endingNode]:[])] : selector === '[data-orbit-card]' ? [card] : []
  const tick = time => { const pending=[...frames.values()];frames.clear();pending.forEach(fn=>fn(time)) }
  const destroy=mountPageOrbit(doc,win)
  return { ...f,doc,win,media,svg,host,styles,card,finale,endingRing,tick,destroy,queued:()=>frames.size,setTop: value=>{top=value},angle:()=>angle }
}

test('全页轨道仅按需绘制，减少动态保留静态线，GPU 丢失恢复并释放资源', () => {
  const f=pageOrbitFixture()
  f.tick(40)
  assert.equal(f.host.dataset.renderer,'webgl');assert.equal(f.queued(),0)
  f.doc.hidden=true;f.doc.dispatchEvent(new Event('visibilitychange'))
  assert.equal(f.queued(),0)
  f.doc.hidden=false;f.doc.dispatchEvent(new Event('visibilitychange'));f.tick(80)
  f.canvases[0].fire('webglcontextlost');f.tick(120)
  assert.equal(f.host.dataset.renderer,'fallback');assert.equal(f.queued(),0)
  assert.ok(f.svg.innerHTML.includes('<path'))
  f.canvases[0].fire('webglcontextrestored');f.tick(160)
  assert.equal(f.host.dataset.renderer,'webgl')
  f.media[0].matches=true;f.media[0].dispatchEvent(new Event('change'));f.tick(200)
  assert.equal(f.host.dataset.renderer,'fallback');assert.equal(f.queued(),0)
  assert.equal(f.angle(),'0deg');assert.equal(f.canvases[0].hidden,true)
  f.media[0].matches=false;f.setTop(-2000);f.win.dispatchEvent(new Event('scroll'));f.tick(240)
  assert.equal(f.host.hidden,true);assert.equal(f.queued(),0)
  f.destroy()
  assert.equal(f.counters.programs,0);assert.equal(f.counters.buffers,0)
  assert.ok(f.canvases[0].removed)
  f.win.dispatchEvent(new Event('resize'));assert.equal(f.queued(),0)
  const unavailable=pageOrbitFixture({unavailable:true});unavailable.tick(40)
  assert.equal(unavailable.host.dataset.renderer,'fallback');assert.ok(unavailable.svg.innerHTML.includes('<path'))
  unavailable.destroy()
})

test('首屏有限出场共用轨道测量帧，结束及卸载后不继续绘制', () => {
  const f = pageOrbitFixture()
  f.tick(0)
  const initial = f.svg.innerHTML
  f.setTop(90)
  f.win.dispatchEvent(new Event('hero:entrance-frame'))
  f.win.dispatchEvent(new Event('hero:entrance-frame'))
  assert.equal(f.queued(), 1)
  f.tick(16)
  assert.notEqual(f.svg.innerHTML, initial)
  assert.equal(f.queued(), 0)
  f.destroy()
  f.win.dispatchEvent(new Event('hero:entrance-frame'))
  assert.equal(f.queued(), 0)
})

// 直接验证滚动几何而不是计时动画，覆盖同位置重放、反向与边界连续性。
test('轨道弧长进度跟随阅读线，向下推进、倒滚收回且边界连续', () => {
  const path = cubicPoints([100,600],[100,800],[900,1000],[900,1200])
  const shift = delta => path.map(([x,y])=>[x,y-delta])
  const start = orbitProgress(path,900), middle = orbitProgress(shift(300),900)
  assert.ok(start > 0 && start < middle && middle < 1)
  assert.equal(orbitProgress(shift(700),900),1)
  assert.equal(orbitProgress(shift(-200),900),0)
  assert.equal(orbitProgress(shift(300),900),middle)
  assert.equal(orbitProgress(path,900),start)
  for (const delta of [83.9,84,84.1,599.9,600,600.1]) {
    assert.ok(Math.abs(orbitProgress(shift(delta+.01),900)-orbitProgress(shift(delta),900))<.001)
  }
  assert.equal(orbitProgress([[NaN,0],[0,100]],900),0)
  assert.equal(orbitProgress([],900),0)
  assert.equal(orbitProgress([[0,0],[0,0]],900),1)
})

test('卡片按滚动入场、中央完整阅读、退场，手机轻量位移与减少动态完整可读', () => {
  const bounds = top => ({top,height:600})
  const entering = orbitCardPose(bounds(750),900), reading = orbitCardPose(bounds(168),900), leaving = orbitCardPose(bounds(-400),900)
  assert.equal(entering.phase,'entering');assert.ok(entering.y>0 && entering.scale<1 && entering.opacity<1)
  assert.equal(reading.phase,'reading');assert.equal(reading.scale,1);assert.equal(reading.opacity,1);assert.equal(reading.angle,0)
  assert.equal(leaving.phase,'leaving');assert.ok(leaving.y<0)
  assert.equal(orbitCardPose(bounds(750),900,1).x,-entering.x)
  assert.deepEqual(orbitCardPose(bounds(750),900),entering)
  const mobile=orbitCardPose(bounds(750),900,0,true)
  assert.equal(mobile.x,0);assert.equal(mobile.angle,0);assert.ok(mobile.y>0 && mobile.y<entering.y);assert.ok(mobile.opacity>=.55)
  assert.deepEqual(orbitCardPose(bounds(750),900,0,false,true),reading)
  // 阅读平台两侧接缝使用零斜率平滑曲线，微量滚动不会造成姿态突变。
  for(let top=-900;top<1200;top+=5) {
    const a=orbitCardPose(bounds(top),900), b=orbitCardPose(bounds(top+.1),900)
    assert.ok(Math.abs(a.y-b.y)<.05);assert.ok(Math.abs(a.opacity-b.opacity)<.001)
  }
})

test('高频滚动每帧合并到最新位置，暂停不漂移，倒滚和快速跳转可重复', () => {
  const f=pageOrbitFixture({unavailable:true});f.tick(1)
  const first=f.svg.innerHTML, pose={...f.styles}
  assert.equal(f.queued(),0)
  f.tick(10000);assert.equal(f.svg.innerHTML,first);assert.deepEqual(f.styles,pose)
  // 16ms 内更新同样必须绘制，避免原 32ms 限速导致连线落后页面。
  f.setTop(-200);f.win.dispatchEvent(new Event('scroll'));f.win.dispatchEvent(new Event('scroll'))
  assert.equal(f.queued(),1);f.tick(16)
  assert.notEqual(f.svg.innerHTML,first);assert.notDeepEqual(f.styles,pose);assert.equal(f.queued(),0)
  f.setTop(-2000);f.win.dispatchEvent(new Event('scroll'));f.tick(17);assert.equal(f.host.hidden,true)
  f.setTop(120);f.win.dispatchEvent(new Event('scroll'));f.tick(18)
  assert.equal(f.svg.innerHTML,first);assert.deepEqual(f.styles,pose)
  f.media[1].matches=true;f.media[1].dispatchEvent(new Event('change'));f.tick(19)
  assert.equal(f.styles['--orbit-angle'],'0deg');assert.equal(f.host.dataset.renderer,'fallback')
  f.media[0].matches=true;f.media[0].dispatchEvent(new Event('change'));f.tick(20)
  assert.equal(f.styles['--orbit-opacity'],'1');assert.equal(f.styles['--orbit-y'],'0px')
  f.destroy();assert.deepEqual(f.styles,{});assert.equal(f.card.dataset.orbitPhase,undefined)
})

test('吸顶舞台节点使用自然位置，端点随页面等距平移，GPU 回退不改路径', () => {
  const f=pageOrbitFixture({sticky:true});f.tick(1)
  const state=()=>[...f.svg.innerHTML.matchAll(/<path d="([^"]+)"/g)].map(match=>match[1])
  f.setTop(-600);f.win.dispatchEvent(new Event('scroll'));f.tick(2)
  const before=state()[0]
  f.setTop(-610);f.win.dispatchEvent(new Event('scroll'));f.tick(3)
  const after=state()[0]
  // 两个节点此时都高于阅读线，路径完整；sticky 标题停在 48px，轨道仍平移 10px。
  const ys = path=>[...path.matchAll(/[ML]([-\d.]+) ([-\d.]+)/g)].map(match=>Number(match[2]))
  ys(before).forEach((y,index)=>assert.ok(Math.abs(ys(after)[index]-(y-10))<.02))
  f.canvases[0].fire('webglcontextlost');f.tick(4)
  assert.equal(f.host.dataset.renderer,'fallback');assert.equal(state()[0],after)
  f.destroy()
})

test('三窗真实明细放大使用独立画布，切换沙盒后恢复原镜头画布', () => {
  const f = scrollingScene({real:true})
  for (const pane of f.windows) {
    assert.equal(pane.style['--logical-width'],'720px')
    assert.equal(pane.style['--logical-height'],'480px')
  }
  f.click('[data-surface-select]',{surfaceSelect:'sandbox'});f.tick(40)
  assert.equal(f.scene.dataset.surface,'sandbox')
  assert.equal(f.windows[1].style['--logical-width'],'1000px')
  f.click('[data-surface-select]',{surfaceSelect:'screenshots'});f.tick(80)
  assert.equal(f.windows[1].style['--logical-width'],'720px')
  assert.equal(f.scene.dataset.mode,'scroll')
  f.destroy()
})

// 连续放大与相机使用同一帧，倒滚可复现，停止滚动后不能继续漂移。
test('真实组件倍率随滚动连续变化，聚焦放大收敛后停帧',()=>{
  const f=scrollingScene({real:true})
  f.scroll(.2);f.tick(16)
  const original=Number(f.realPanes[0].style['--detail-zoom'])
  assert.ok(original>2/3 && original<1)
  f.scroll(.3);f.tick(32)
  const midway=Number(f.realPanes[0].style['--detail-zoom'])
  assert.ok(midway>original && midway<1)
  f.scroll(.45);f.tick(48);assert.equal(Number(f.realPanes[0].style['--detail-zoom']),1)
  f.scroll(.2);f.tick(64);assert.equal(Number(f.realPanes[0].style['--detail-zoom']),original)
  assert.equal(f.queued(),0)
  f.click('[data-focus]',{focus:'receipt'});f.tick(80);f.tick(96)
  assert.ok(Number(f.realPanes[0].style['--detail-zoom'])>original)
  for(let time=112;time<2400;time+=16)f.tick(time)
  assert.equal(Number(f.realPanes[0].style['--detail-zoom']),1);assert.equal(f.queued(),0)
  f.destroy()
})

// 测试共用几何的阅读边界、移动视口和静态偏好，不复制椭圆计算实现。
test('收尾轨道仅在可见时展开，倒滚可逆且减少动态保留完整线', () => {
  assert.deepEqual(finaleOrbit({top:900,height:640},1440,900), [])
  assert.deepEqual(finaleOrbit({top:-640,height:640},1440,900), [])
  assert.deepEqual(finaleOrbit({top:NaN,height:640},1440,900), [])
  assert.deepEqual(finaleOrbit({top:0,height:640},0,900), [])
  const entering = finaleOrbit({top:780,height:640},1440,900)
  const reading = finaleOrbit({top:120,height:640},1440,900)
  assert.equal(reading.length,2)
  assert.ok(entering[0].amount < reading[0].amount)
  assert.deepEqual(finaleOrbit({top:780,height:640},1440,900),entering)
  const nearby = finaleOrbit({top:779.99,height:640},1440,900)
  assert.ok(Math.abs(nearby[0].amount-entering[0].amount)<.001)
  const phone = finaleOrbit({top:100,height:460},390,844,true)
  for(const line of phone){
    assert.equal(line.amount,1)
    assert.ok(line.points.flat().every(Number.isFinite))
    assert.ok(line.points.every(([x])=>x>=0&&x<=390))
  }
})

test('收尾复用全页画布，GPU 失败仍显示 SVG 且离屏不维持循环', () => {
  for(const unavailable of [false,true]){
    const f=pageOrbitFixture({finale:true,unavailable})
    f.tick(0);f.setTop(-2100);f.win.dispatchEvent(new Event('scroll'));f.tick(16)
    assert.equal(f.host.dataset.renderer,unavailable?'fallback':'webgl')
    assert.equal(f.host.hidden,false)
    assert.equal(f.canvases.length,1)
    assert.equal((f.svg.innerHTML.match(/<path/g)||[]).length,2)
    assert.equal(f.finale.dataset.orbitReady,'true')
    assert.equal(f.queued(),0)
    f.setTop(-3000);f.win.dispatchEvent(new Event('scroll'));f.tick(32)
    assert.equal(f.host.hidden,true);assert.equal(f.queued(),0)
    f.destroy();assert.equal(f.finale.dataset.orbitReady,undefined)
  }
})

// 主线沿切线顺滑汇入，倾斜主辅轨道同心闭合且不进入标题的核心区域。
test('收尾倾斜轨道同心闭合，主线顺着轨道切线自然汇入', () => {
  const background = {left:80,top:190,width:1000,height:330}
  const geometry = finaleGeometry({top:100,height:640},1440,background)
  for(const points of [geometry.points,geometry.secondary]){
    assert.deepEqual(points[0],points.at(-1))
    assert.ok(points.every(([x,y])=>Math.abs(x-580)>230 || Math.abs(y-355)>85))
  }
  // 左下方接点沿弧度继续轻缓绕行，接入本身不出现先向右再折返的回钩。
  assert.ok(geometry.entry[0]<580 && geometry.entry[1]>355)
  assert.ok(geometry.tangent[0]>0 && geometry.tangent[1]>0)
  const [incoming] = pageOrbitSegments([[80,30],geometry.entry],1440,900,false,geometry.tangent)
  assert.deepEqual(incoming.points.at(-1),geometry.entry)
  const before = incoming.points.at(-2), after=geometry.points[1],entry=geometry.entry
  const a=[entry[0]-before[0],entry[1]-before[1]],b=[after[0]-entry[0],after[1]-entry[1]]
  assert.ok((a[0]*b[0]+a[1]*b[1])/(Math.hypot(...a)*Math.hypot(...b))>.995)
  assert.deepEqual(finaleOrbit({top:100,height:640},1440,900,false,{...background,width:0}),[])
  assert.deepEqual(finaleOrbit({top:100,height:640},1440,900,false,{...background,top:NaN}),[])
})

// 实页装配必须使用背景的实测尺寸，而不是视口中心或隐藏标记的位置。
test('收尾接入与闭环使用同一实测几何，下载位置承担正文末尾转弯', () => {
  const f=pageOrbitFixture({finale:true,ending:true})
  f.setTop(-2100);f.tick(0)
  const geometry=finaleGeometry(f.finale.getBoundingClientRect(),1440,f.endingRing.getBoundingClientRect())
  const paths=[...f.svg.innerHTML.matchAll(/<path d="([^"]+)"/g)].map(match=>match[1])
  assert.equal(paths.length,4)
  const junction=geometry.entry.map(value=>value.toFixed(2)).join(' ')
  assert.ok(paths[1].endsWith('L'+junction))
  assert.ok(paths[2].startsWith('M'+junction))
  assert.equal(f.queued(),0)
  f.destroy()
})
