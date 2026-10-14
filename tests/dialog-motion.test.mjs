import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ref } from 'vue'
import { captureDialogOrigin, getDialogOrigin, releaseDialogOrigin, clearDialogOrigins, visibleDialogOrigin, onDialogOriginCaptured, registerDialogOriginSnapshot } from '../src/renderer/src/utils/dialog-origin.ts'
import { dialogOriginFrame, createDialogMotionController } from '../src/renderer/src/utils/dialog-motion.ts'
import { createDialogPreparationBarrier, onDialogPresentationInvalidated, invalidateDialogPresentations } from '../src/renderer/src/composables/use-dialog-presentation.ts'

function source(rect = { left: 20, top: 30, width: 80, height: 36 }) {
  return { isConnected: true, getBoundingClientRect: () => rect }
}
test('每个入口独立登记，键盘事件使用 currentTarget；无来源打开不会借用上一次点击', () => {
  clearDialogOrigins()
  const a = source(), b = source({ left: 220, top: 130, width: 40, height: 30 })
  const first = captureDialogOrigin('details-a', { currentTarget: a, target: b })
  captureDialogOrigin('details-b', b)
  assert.equal(getDialogOrigin('details-a').element, a)
  assert.equal(getDialogOrigin('details-b').element, b)
  assert.equal(getDialogOrigin('never-opened'), null)
  const newer = captureDialogOrigin('details-a', b)
  releaseDialogOrigin('details-a', first)
  assert.equal(getDialogOrigin('details-a'), newer)
  captureDialogOrigin('details-a', null)
  assert.equal(getDialogOrigin('details-a'), null)
})
test('回程重测来源，脱离页面或已滚出视口时降级淡出', () => {
  const rect = { left: 20, top: 30, width: 80, height: 36 }, button = source(rect)
  const origin = captureDialogOrigin('moving', button), viewport = { width: 800, height: 600 }
  rect.left = 310
  assert.equal(visibleDialogOrigin(origin, viewport).left, 310)
  for (const change of [{ top: 650 }, { left: -90 }, { width: 0 }, { top: NaN }]) {
    Object.assign(rect, { left: 20, top: 30, width: 80, height: 36 }, change)
    assert.equal(visibleDialogOrigin(origin, viewport), null)
  }
  Object.assign(rect, { left: 20, top: 30, width: 80, height: 36 })
  button.isConnected = false
  assert.equal(visibleDialogOrigin(origin, viewport), null)
})
test('按钮矩形准确映射到窗口，减少动态效果不包含位移或缩放', () => {
  const target = { left: 200, top: 100, width: 800, height: 600 }, origin = { left: 20, top: 30, width: 80, height: 36 }
  assert.equal(dialogOriginFrame(target, origin, '12px').transform, 'translate(-180px, -70px) scale(0.1, 0.06)')
  assert.equal(dialogOriginFrame(target, origin, '12px', true).transform, 'none')
  assert.equal(dialogOriginFrame(target, null, '12px').opacity, '0')
})
function animationElement() {
  const runs = []
  const element = { style: {}, animate(frames, options) {
    let finish, reject
    const animation = { finished: new Promise((resolve, fail) => { finish = resolve; reject = fail }), cancel: () => reject(new Error('cancelled')) }
    runs.push({ frames, options, finish, animation }); return animation
  } }
  return { element, runs }
}
test('快速反向只让最后一轮完成，取消的旧 finished 不能覆盖新画面', async () => {
  const motion = createDialogMotionController(), { element, runs } = animationElement()
  const from = { transform: 'scale(.1)', opacity: '0', borderRadius: '12px' }
  const to = { transform: 'none', opacity: '1', borderRadius: '20px' }
  const first = motion.play(element, from, to, 360)
  const midway = { transform: 'scale(.6)', opacity: '.6', borderRadius: '16px' }
  const last = motion.play(element, midway, from, 280)
  assert.equal(await first, false)
  assert.deepEqual(runs[1].frames[0], midway)
  runs[1].finish()
  assert.equal(await last, true)
  assert.equal(element.style.transform, 'scale(.1)')
})
test('无 WAAPI 的环境仍可正确结束显示，安全失效取消在途动画', async () => {
  const motion = createDialogMotionController(), frame = { transform: 'none', opacity: '1', borderRadius: '0' }
  const plain = { style: {} }
  assert.equal(await motion.play(plain, frame, frame, 360), true)
  const { element } = animationElement(), pending = motion.play(element, frame, frame, 360)
  motion.cancel()
  assert.equal(await pending, false)
})
test('首屏屏障等待所有历史读取，失败与子组件卸载会更新所属窗口', () => {
  const barrier = createDialogPreparationBarrier(), first = ref(true), second = ref(true), error = ref('')
  barrier.register({ pending: first, error })
  const unregister = barrier.register({ pending: second })
  first.value = false
  assert.equal(barrier.pending.value, true)
  second.value = false
  assert.equal(barrier.pending.value, false)
  error.value = '历史读取失败'
  assert.equal(barrier.error.value, '历史读取失败')
  second.value = true; unregister()
  assert.equal(barrier.pending.value, false)
})
test('会话失效同时销毁所有窗口和来源，已卸载的窗口不会被再次调用', () => {
  let first = 0, second = 0
  const stopFirst = onDialogPresentationInvalidated(() => first++)
  const stopSecond = onDialogPresentationInvalidated(() => second++)
  captureDialogOrigin('private-data', source())
  stopSecond(); invalidateDialogPresentations(); stopFirst()
  assert.equal(first, 1); assert.equal(second, 0)
  assert.equal(getDialogOrigin('private-data'), null)
})

test('等待中相同 key 的新入口及时通知，其他窗口与已取消订阅不受影响', () => {
  const seen = [], other = []
  const stop = onDialogOriginCaptured('pending-a', origin => seen.push(origin?.element ?? null))
  const stopOther = onDialogOriginCaptured('pending-b', origin => other.push(origin))
  const first = source(), second = source()
  captureDialogOrigin('pending-a', first); captureDialogOrigin('pending-a', second)
  captureDialogOrigin('pending-a', null); stop(); captureDialogOrigin('pending-a', first); stopOther()
  assert.deepEqual(seen, [first, second, null]); assert.equal(other.length, 0)
})
test('表格 overflow 祖先裁掉的入口不能作为回程目标，部分可见只使用交集', t => {
  const previous = globalThis.getComputedStyle
  t.after(() => { if (previous) globalThis.getComputedStyle = previous; else delete globalThis.getComputedStyle })
  globalThis.getComputedStyle = element => element.style ?? { visibility: 'visible', display: 'block' }
  const button = source({ left: 30, top: 200, width: 80, height: 36 })
  const parent = { style: { overflowX: 'hidden', overflowY: 'auto' }, clientLeft: 0, clientTop: 0, clientWidth: 150, clientHeight: 100,
    getBoundingClientRect: () => ({ left: 0, top: 50 }), parentElement: null }
  button.parentElement = parent
  const origin = captureDialogOrigin('clipped', button)
  assert.equal(visibleDialogOrigin(origin, { width: 800, height: 600 }), null)
  parent.clientHeight = 170
  assert.deepEqual(visibleDialogOrigin(origin, { width: 800, height: 600 }), { left: 30, top: 200, width: 80, height: 20 })
  button.style = { visibility: 'hidden' }
  assert.equal(visibleDialogOrigin(origin, { width: 800, height: 600 }), null)
})
test('父窗口暂时隐藏入口时只使用对应可见快照，副本消失后仍降级淡出', t => {
  const previous = globalThis.getComputedStyle
  t.after(() => { if (previous) globalThis.getComputedStyle = previous; else delete globalThis.getComputedStyle })
  globalThis.getComputedStyle = element => element.style ?? { visibility: 'visible', display: 'block' }
  const button = source(), copy = source({ left: 240, top: 160, width: 90, height: 32 })
  const origin = captureDialogOrigin('nested-copy', button), viewport = { width: 800, height: 600 }
  button.style = { visibility: 'hidden' }
  const release = registerDialogOriginSnapshot([button], [copy])
  assert.deepEqual(visibleDialogOrigin(origin, viewport), { left: 240, top: 160, width: 90, height: 32 })
  copy.isConnected = false
  assert.equal(visibleDialogOrigin(origin, viewport), null)
  copy.isConnected = true; release()
  assert.equal(visibleDialogOrigin(origin, viewport), null)
})
