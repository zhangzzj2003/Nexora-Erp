import { MAX_TABLE_COLUMN_WIDTH, MIN_TABLE_COLUMN_WIDTH } from './table-column-widths.ts'

export interface TableColumnResizeOptions {
  startX: number
  startWidth: number
  // 右侧冻结区的手柄位于左边界，向左拖才是加宽。
  direction: 1 | -1
  maxWidth?: number
  schedule: (callback: () => void) => number
  unschedule: (id: number) => void
  preview: (width: number) => Promise<unknown>
  commit: (width: number) => void
  restore: () => Promise<void>
  onError: (error: unknown) => void
}

// 把高频鼠标移动合并到绘制帧；预览串行执行，松手后才保存，取消时恢复原布局。
export function createTableColumnResize(options: TableColumnResizeOptions) {
  let width = options.startWidth
  let active = true
  let cancelled = false
  let failed = false
  let revision = 0
  let frame: number | undefined
  let work = Promise.resolve()
  const clearFrame = () => {
    if (frame !== undefined) options.unschedule(frame)
    frame = undefined
  }
  const preview = () => {
    const current = ++revision
    const nextWidth = width
    // 若刷新还未完成，只应用最新位置，避免旧帧在松手后又覆盖最终宽度。
    work = work.then(async () => {
      if (!cancelled && current === revision) await options.preview(nextWidth)
    }).catch(error => { failed = true; options.onError(error) })
  }
  const move = (clientX: number) => {
    if (!active || !Number.isFinite(clientX)) return
    width = Math.max(MIN_TABLE_COLUMN_WIDTH, Math.min(options.maxWidth ?? MAX_TABLE_COLUMN_WIDTH,
      Math.round(options.startWidth + (clientX - options.startX) * options.direction)))
    if (frame === undefined) frame = options.schedule(() => { frame = undefined; preview() })
  }
  return {
    move,
    async finish(clientX: number): Promise<void> {
      if (!active) return
      move(clientX)
      active = false
      clearFrame()
      preview()
      await work
      if (failed) await options.restore()
      else options.commit(width)
    },
    async cancel(): Promise<void> {
      if (!active) return
      active = false
      cancelled = true
      ++revision
      clearFrame()
      await work
      await options.restore()
    }
  }
}
