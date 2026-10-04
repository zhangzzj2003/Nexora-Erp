import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createThemeTransition, themeCircleFrames, themeToggleOrigin } from '../src/renderer/src/utils/theme-transition.ts'

// 可控制的浏览器快照模拟隐藏窗口、失败和连续点击，不依赖真实动画计时。
function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const tick = () => new Promise(resolve => setImmediate(resolve))
function setup({ supported = true, reducedMotion = false, manual = false, fail, timeoutMs = 30 } = {}) {
  let dark = false, animation
  const writes = [], calls = [], snapshots = []
  const root = { dataset: {}, animate(frames, options) {
    calls.push({ frames, options })
    if (fail === 'animate') throw new Error('animation unavailable')
    const end = deferred()
    if (!manual) end.resolve()
    animation = { finished: end.promise, cancel() { end.reject(new Error('cancelled')) }, end }
    return animation
  } }
  const env = { width: 800, height: 600, reducedMotion, root, start: supported ? update => {
    if (fail === 'start') throw new Error('capture unavailable')
    const ready = deferred(), finished = deferred()
    const snapshot = { ready: ready.promise, finished: finished.promise, skipTransition() { finished.resolve() }, update, readyControl: ready }
    snapshots.push(snapshot)
    if (!manual) void update().then(() => fail === 'ready' ? ready.reject(new Error('hidden')) : ready.resolve())
    return snapshot
  } : undefined }
  const motion = createThemeTransition({ isDark: () => dark, setDark: value => { dark = value; writes.push(value) }, flush: async () => {}, environment: () => env, timeoutMs })
  return { motion, root, calls, snapshots, writes, animation: () => animation, dark: () => dark }
}

test('百分比圆形在横竖窗口与不同像素密度下都从按钮展开、覆盖全部角落', () => {
  // 按 CSS 百分比规则还原物理裁剪区域，避免暂停截图掩盖合成阶段的 px 缩放问题。
  for (const [width, height] of [[800, 600], [1120, 720], [600, 1000], [3580, 2332]]) {
    for (const origin of [{ x: width - 29, y: 24 }, { x: 20, y: 24 }, { x: width / 2, y: height / 2 }]) {
      const frames = themeCircleFrames(origin, width, height)
      for (const density of [1, 1.25, 2, 3]) {
        const physicalWidth = width * density, physicalHeight = height * density
        const circles = frames.map(frame => {
          const match = /^circle\(([\d.]+)% at ([\d.]+)% ([\d.]+)%\)$/.exec(frame)
          assert.ok(match, '圆心和半径必须全部使用百分比，不能混入 px')
          return {
            radius: Number(match[1]) / 100 * Math.hypot(physicalWidth, physicalHeight) / Math.SQRT2,
            x: Number(match[2]) / 100 * physicalWidth, y: Number(match[3]) / 100 * physicalHeight
          }
        })
        assert.equal(circles[0].radius, 0)
        for (const circle of circles) {
          assert.ok(Math.abs(circle.x - origin.x * density) < 1e-6)
          assert.ok(Math.abs(circle.y - origin.y * density) < 1e-6)
        }
        for (const x of [0, physicalWidth]) for (const y of [0, physicalHeight]) {
          assert.ok(circles[1].radius > Math.hypot(x - circles[1].x, y - circles[1].y))
        }
      }
    }
  }
})
test('鼠标以点击坐标为圆心，键盘以按钮中心为圆心', () => {
  const rect = { left: 100, top: 20, width: 32, height: 32 }
  assert.deepEqual(themeToggleOrigin({ detail: 1, clientX: 105, clientY: 25 }, rect), { x: 105, y: 25 })
  assert.deepEqual(themeToggleOrigin({ detail: 0, clientX: 0, clientY: 0 }, rect), { x: 116, y: 36 })
  // 包装层转发的合成坐标或越界坐标也必须回到按钮，而不是窗口中心。
  assert.deepEqual(themeToggleOrigin({ detail: 1, clientX: 0, clientY: 0 }, rect), { x: 116, y: 36 })
  assert.deepEqual(themeToggleOrigin({ detail: 1, clientX: NaN, clientY: 25 }, rect), { x: 116, y: 36 })
})
test('明暗切换使用正确快照、450ms节奏，结束释放样式', async () => {
  const s = setup()
  await s.motion.toggle({ x: 30, y: 40 })
  assert.equal(s.dark(), true)
  assert.equal(s.calls[0].options.pseudoElement, '::view-transition-new(root)')
  assert.equal(s.calls[0].options.duration, 450)
  assert.equal(s.calls[0].options.easing, 'ease-in')
  await s.motion.toggle()
  assert.equal(s.dark(), false)
  assert.equal(s.calls[1].options.pseudoElement, '::view-transition-new(root)')
  assert.equal(s.calls[1].frames.clipPath[0], 'circle(0% at 50% 50%)')
  assert.deepEqual(s.root.dataset, {})
})
for (const options of [{ supported: false }, { reducedMotion: true }]) {
  test(`不支持快照或减少动态效果时直接提交主题 ${JSON.stringify(options)}`, async () => {
    const s = setup(options)
    await s.motion.toggle()
    assert.equal(s.dark(), true)
    assert.equal(s.snapshots.length, 0)
    assert.equal(s.calls.length, 0)
    assert.deepEqual(s.root.dataset, {})
  })
}
for (const fail of ['start', 'ready', 'animate']) {
  test(`快照${fail}失败仍提交主题并释放遮罩`, async () => {
    const s = setup({ fail })
    await s.motion.toggle()
    assert.deepEqual(s.writes, [true])
    assert.deepEqual(s.root.dataset, {})
  })
}
test('快照超时后迟到的ready和更新回调不能复活动画', async () => {
  const s = setup({ manual: true, timeoutMs: 5 })
  await s.motion.toggle()
  assert.equal(s.dark(), true)
  s.snapshots[0].readyControl.resolve()
  await s.snapshots[0].update()
  await tick()
  assert.equal(s.calls.length, 0)
  assert.deepEqual(s.writes, [true])
  assert.deepEqual(s.root.dataset, {})
})
test('未开始的连续点击保留奇偶结果和最后点击圆心', async () => {
  const s = setup()
  await Promise.all([s.motion.toggle(), s.motion.toggle()])
  assert.equal(s.dark(), false)
  assert.equal(s.calls.length, 0)
  await Promise.all([s.motion.toggle(), s.motion.toggle(), s.motion.toggle({ x: 7, y: 8 })])
  assert.equal(s.dark(), true)
  assert.equal(s.calls[0].frames.clipPath[0], themeCircleFrames({ x: 7, y: 8 }, 800, 600)[0])
})
test('设置卡片明确选择主题，与顶部切换共用最后一次意图', async () => {
  const s = setup()
  // 重复选中同一主题不反转；混合点击和快速切换按最后的明确选择提交。
  await Promise.all([s.motion.select(true), s.motion.select(true)])
  assert.equal(s.dark(), true)
  assert.deepEqual(s.writes, [true])
  await Promise.all([s.motion.toggle(), s.motion.select(true), s.motion.select(false)])
  assert.equal(s.dark(), false)
  const count = s.calls.length
  await s.motion.select(false)
  assert.equal(s.calls.length, count)
})
test('设置选择覆盖在途快照，迟到更新不能覆盖最终主题', async () => {
  const s = setup({ manual: true, timeoutMs: 5 })
  const first = s.motion.select(true)
  // 只刷新微任务，让快照开始但不让真实计时器抢先触发超时。
  await Promise.resolve()
  const second = s.motion.select(false)
  await Promise.all([first, second])
  await s.snapshots[0].update()
  s.snapshots[0].readyControl.resolve()
  await tick()
  assert.equal(s.dark(), false)
  assert.deepEqual(s.root.dataset, {})
})
test('快照等待期间的连续点击取消旧请求，迟到回调不能覆盖最后主题', async () => {
  const s = setup({ manual: true, timeoutMs: 5 })
  const first = s.motion.toggle()
  // 连续点击应发生在同一轮事件循环，避免繁忙 CI 的 setImmediate 落后于 5ms 超时。
  await Promise.resolve()
  const second = s.motion.toggle()
  await Promise.all([first, second])
  await s.snapshots[0].update()
  s.snapshots[0].readyControl.resolve()
  await tick()
  assert.equal(s.dark(), false)
  assert.deepEqual(s.writes, [])
  assert.deepEqual(s.root.dataset, {})
})
test('已提交主题后的第二次点击和store销毁都能取消在途动画', async () => {
  const s = setup({ manual: true, timeoutMs: 1000 })
  const first = s.motion.toggle()
  await tick()
  await s.snapshots[0].update()
  s.snapshots[0].readyControl.resolve()
  await tick()
  assert.equal(s.calls.length, 1)
  const second = s.motion.toggle()
  await Promise.all([first, second])
  assert.equal(s.dark(), false)
  const third = s.motion.toggle()
  await tick()
  s.motion.dispose()
  await third
  await s.snapshots.at(-1).update()
  await s.motion.toggle()
  assert.equal(s.dark(), false)
  assert.deepEqual(s.root.dataset, {})
})

// 在中途仍保留遮罩和终态配色，动画完成后才能清理，防止半途露出真实页面。
test('圆形未完全展开时不能释放快照或恢复颜色过渡', async () => {
  const s = setup({ manual: true, timeoutMs: 1000 })
  const request = s.motion.toggle({ x: 780, y: 20 })
  await tick()
  await s.snapshots[0].update()
  s.snapshots[0].readyControl.resolve()
  await tick()
  assert.equal(s.root.dataset.themeTransition, 'circle')
  assert.equal(s.calls.length, 1)
  assert.equal(s.calls[0].frames.clipPath[0], themeCircleFrames({ x: 780, y: 20 }, 800, 600)[0])
  // 等待的动画句柄由模拟浏览器返回，完成前不允许快照结束。
  s.animation().end.resolve()
  await request
  assert.deepEqual(s.root.dataset, {})
})
