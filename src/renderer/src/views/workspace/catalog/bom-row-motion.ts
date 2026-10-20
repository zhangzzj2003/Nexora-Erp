import { onBeforeUnmount, shallowRef, watch, type ComputedRef } from 'vue'
import type { BomStructureRow } from './bom-structure'

// 离场行保留在原分支位置，操作权限与物料身份仍以逻辑目录为准。
export function retainLeavingBomRows(previous: readonly BomStructureRow[], next: readonly BomStructureRow[]): BomStructureRow[] {
  const result = [...next]
  const live = new Set(next.map(row => row.key))
  let anchor = -1
  for (const row of previous) {
    if (live.has(row.key)) anchor = result.findIndex(item => item.key === row.key)
    else result.splice(++anchor, 0, row)
  }
  return result
}

interface CellFrame extends Keyframe { height: string; paddingTop: string; paddingBottom: string; opacity: string }
const zero: CellFrame = { height: '0px', paddingTop: '0px', paddingBottom: '0px', opacity: '0' }
function readCell(cell: HTMLElement): CellFrame {
  const style = getComputedStyle(cell)
  return { height: `${cell.getBoundingClientRect().height}px`, paddingTop: style.paddingTop,
    paddingBottom: style.paddingBottom, opacity: style.opacity }
}

// 在共享表格的真实单元格上过渡高度，保留列宽、物料入口与多层缩进。
export function useBomRowMotion(source: ComputedRef<BomStructureRow[]>, identity: () => number,
  root: () => HTMLElement | null, refresh: () => Promise<void>) {
  const displayed = shallowRef(source.value)
  const entering = shallowRef(new Set<string>())
  let generation = 0
  let currentIdentity = identity()
  let animations: Animation[] = []
  let moving = new Set<string>()
  const domRoot = () => typeof HTMLElement !== 'undefined' && root() instanceof HTMLElement ? root() : null
  const elements = (): Map<string, HTMLElement> => new Map(Array.from(
    domRoot()?.querySelectorAll<HTMLElement>('.structure-tree[data-structure-key]') ?? [])
    .flatMap(marker => { const row = marker.closest('tr'); return row ? [[marker.dataset.structureKey!, row] as const] : [] }))
  const cells = (row: HTMLElement): HTMLElement[] => Array.from(row.querySelectorAll<HTMLElement>(':scope > td > .vxe-cell'))
  function cancel(): void {
    animations.forEach(animation => animation.cancel())
    animations = []
    for (const row of elements().values()) {
      delete row.dataset.bomMotion
      row.inert = false
      row.removeAttribute('aria-hidden')
    }
  }
  async function update(next: BomStructureRow[]): Promise<void> {
    const ticket = ++generation
    const before = elements()
    const oldKeys = new Set(displayed.value.map(row => row.key))
    const wanted = new Set(next.map(row => row.key))
    const changed = new Set([...moving, ...next.filter(row => !oldKeys.has(row.key)).map(row => row.key),
      ...displayed.value.filter(row => !wanted.has(row.key)).map(row => row.key)])
    // 反向点击从当前可见高度继续；先测量再取消，避免跳回上一轮起点。
    const frames = new Map([...before].map(([key, row]) => [key, cells(row).map(readCell)]))
    cancel()
    const reset = currentIdentity !== identity()
    currentIdentity = identity()
    if (reset || !domRoot() || !changed.size || typeof Element.prototype.animate !== 'function'
      || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      moving = new Set()
      entering.value = new Set()
      displayed.value = next
      return
    }
    moving = changed
    entering.value = new Set(next.filter(row => !before.has(row.key)).map(row => row.key))
    for (const [key, row] of before) {
      if (changed.has(key)) {
        row.dataset.bomMotion = 'true'
        // 等待表格更新时也保持当前几何，快速反向不能先闪出完整高度。
        cells(row).forEach((cell, index) => {
          const frame = frames.get(key)![index]
          animations.push(cell.animate([frame, frame], { duration: 1, fill: 'both' }))
        })
      }
      if (!wanted.has(key)) {
        if (row.contains(document.activeElement)) {
          let ancestor = key
          while (ancestor.includes('/')) {
            ancestor = ancestor.slice(0, ancestor.lastIndexOf('/'))
            if (wanted.has(ancestor)) { before.get(ancestor)?.querySelector<HTMLButtonElement>('.structure-toggle')?.focus(); break }
          }
        }
        // 离场内容立即退出键盘和读屏访问，名称详情与配方入口一起锁定。
        row.inert = true
        row.setAttribute('aria-hidden', 'true')
      }
    }
    displayed.value = retainLeavingBomRows(displayed.value, next)
    try {
      await refresh()
      if (ticket !== generation) return
      const rendered = elements()
      animations.forEach(animation => animation.cancel())
      animations = []
      // 同一帧清除入场占位及 VXE 行高缓存，再测量自然高度，不显示中间测量状态。
      for (const [key, row] of rendered) {
        row.querySelector('[data-structure-entering]')?.removeAttribute('data-structure-entering')
        if (changed.has(key)) cells(row).forEach(cell => { cell.style.height = 'auto' })
      }
      const targets = new Map([...rendered].filter(([key]) => changed.has(key)).map(([key, row]) => [key, cells(row).map(readCell)]))
      for (const [key, row] of rendered) {
        if (!changed.has(key)) continue
        row.dataset.bomMotion = 'true'
        if (!wanted.has(key)) { row.inert = true; row.setAttribute('aria-hidden', 'true') }
        cells(row).forEach((cell, index) => {
          const from = frames.get(key)?.[index] ?? zero
          const to = wanted.has(key) ? targets.get(key)![index] : zero
          animations.push(cell.animate([from, to], { duration: 220, easing: 'cubic-bezier(.16,1,.3,1)', fill: 'both' }))
        })
      }
      entering.value = new Set()
      await Promise.allSettled(animations.map(animation => animation.finished))
      if (ticket !== generation) return
      cancel()
      moving = new Set()
      displayed.value = next
      await refresh()
    } catch (error) {
      // 布局失败不能留下不可操作的旧行；业务目录仍立即落到本次目标状态。
      if (ticket !== generation) return
      cancel()
      moving = new Set()
      entering.value = new Set()
      displayed.value = next
      console.warn('BOM 组成动画布局失败，已恢复当前目录', error)
    }
  }
  watch([source, identity], ([next]) => { void update(next) }, { flush: 'sync' })
  onBeforeUnmount(() => { generation++; cancel() })
  return { displayed, entering }
}
