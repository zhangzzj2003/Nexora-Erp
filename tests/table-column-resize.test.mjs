import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createTableColumnResize } from '../src/renderer/src/utils/table-column-resize.ts'

// 使用可控绘制帧验证真实拖动时序，预览与松手保存必须分开。
function fixture(overrides = {}) {
  let id = 0
  const frames = new Map(), previews = [], commits = [], errors = []
  let restored = 0
  const session = createTableColumnResize({
    startX: 100, startWidth: 200, direction: 1,
    schedule: cb => { frames.set(++id, cb); return id }, unschedule: key => frames.delete(key),
    preview: async width => { previews.push(width) }, commit: width => commits.push(width),
    restore: async () => { restored++ }, onError: error => errors.push(error), ...overrides
  })
  return { session, previews, commits, errors, frames, get restored() { return restored },
    async frame() { const jobs = [...frames.values()]; frames.clear(); jobs.forEach(job => job()); await new Promise(setImmediate) } }
}

test('松手前实时预览，连续移动合并为最新绘制帧，最终位置只保存一次', async () => {
  const f = fixture()
  f.session.move(120)
  f.session.move(150)
  assert.equal(f.frames.size, 1)
  await f.frame()
  assert.deepEqual(f.previews, [250])
  assert.deepEqual(f.commits, [])
  await f.session.finish(160)
  assert.deepEqual(f.previews, [250, 260])
  assert.deepEqual(f.commits, [260])
  assert.equal(f.frames.size, 0)
  await f.session.finish(180)
  f.session.move(190)
  assert.deepEqual(f.commits, [260])
})

test('普通列与右侧冻结列拖动方向正确，并限制最小、最大及冻结区宽度', async () => {
  const left = fixture()
  left.session.move(-1000)
  await left.frame()
  assert.deepEqual(left.previews, [64])
  await left.session.finish(5000)
  assert.deepEqual(left.commits, [2400])
  const right = fixture({ direction: -1, maxWidth: 360 })
  right.session.move(20)
  await right.frame()
  assert.deepEqual(right.previews, [280])
  await right.session.finish(-1000)
  assert.deepEqual(right.commits, [360])
})

test('取消等待正在进行的预览结束后恢复，且不保存或执行排队的旧预览', async () => {
  let release
  const f = fixture({ preview: () => new Promise(resolve => { release = resolve }) })
  f.session.move(150)
  await f.frame()
  f.session.move(180)
  const cancelled = f.session.cancel()
  assert.equal(f.restored, 0)
  release()
  await cancelled
  assert.equal(f.restored, 1)
  assert.deepEqual(f.commits, [])
  assert.equal(f.frames.size, 0)
  await f.session.finish(200)
  assert.deepEqual(f.commits, [])
})

test('异步预览不能在最终保存之后覆盖宽度，过期帧自动丢弃', async () => {
  let release
  const applied = []
  const f = fixture({ preview: async width => {
    if (width === 220) await new Promise(resolve => { release = resolve })
    applied.push(width)
  } })
  f.session.move(120)
  await f.frame()
  f.session.move(140)
  await f.frame()
  const finished = f.session.finish(180)
  assert.deepEqual(f.commits, [])
  release()
  await finished
  assert.deepEqual(applied, [220, 280])
  assert.deepEqual(f.commits, [280])
})

test('布局刷新失败时恢复原宽度，非法鼠标位置不会污染保存值', async () => {
  const failure = new Error('刷新失败')
  const f = fixture({ preview: async () => { throw failure } })
  f.session.move(Number.NaN)
  assert.equal(f.frames.size, 0)
  await f.session.finish(160)
  assert.deepEqual(f.errors, [failure])
  assert.equal(f.restored, 1)
  assert.deepEqual(f.commits, [])
})
