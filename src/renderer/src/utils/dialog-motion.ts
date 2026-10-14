import type { DialogRect } from './dialog-origin'
import { registerDialogOriginSnapshot } from './dialog-origin.ts'

export interface DialogMotionFrame { transform: string; opacity: string; borderRadius: string }
export const dialogMotionTiming = { enter: 360, leave: 280, fade: 140, reduced: 80 } as const
export function dialogOriginFrame(target: DialogRect, origin: DialogRect | null, radius: string, reduced = false): DialogMotionFrame {
  if (!origin || reduced || target.width <= 0 || target.height <= 0) return { transform: 'none', opacity: '0', borderRadius: radius }
  return { transform: `translate(${origin.left - target.left}px, ${origin.top - target.top}px) scale(${origin.width / target.width}, ${origin.height / target.height})`, opacity: '0', borderRadius: radius }
}
export function readDialogFrame(element: HTMLElement): DialogMotionFrame {
  const style = getComputedStyle(element)
  return { transform: style.transform, opacity: style.opacity, borderRadius: style.borderRadius }
}

// 每个控制器只拥有自己的动画；重入先保存当前画面，旧 finished 不能结束新动画。
export function createDialogMotionController() {
  let generation = 0
  let animation: Animation | null = null
  let animatedElement: HTMLElement | null = null
  function cancel(): void { generation++; animation?.cancel(); animation = null; animatedElement = null }
  function capture(): DialogMotionFrame | null { return animatedElement ? readDialogFrame(animatedElement) : null }
  async function play(element: HTMLElement, from: DialogMotionFrame, to: DialogMotionFrame, duration: number): Promise<boolean> {
    cancel()
    const ticket = generation
    animatedElement = element
    Object.assign(element.style, from)
    if (typeof element.animate !== 'function' || duration === 0) {
      Object.assign(element.style, to); animatedElement = null; return true
    }
    animation = element.animate([{ ...from }, { ...to }], { duration, easing: 'cubic-bezier(.22, 1, .36, 1)', fill: 'both' })
    try { await animation.finished } catch { return false }
    if (ticket !== generation) return false
    Object.assign(element.style, to)
    animation.cancel(); animation = null; animatedElement = null
    return true
  }
  return { play, capture, cancel }
}

export interface DialogExitFrame { element: HTMLElement; restoreScroll: () => void; remove: () => void }
export function cloneDialogExitFrame(source: HTMLElement, bounds: DialogRect): DialogExitFrame {
  const clone = source.cloneNode(true) as HTMLElement
  const originalNodes = [source, ...source.querySelectorAll<HTMLElement>('*')]
  const copiedNodes = [clone, ...clone.querySelectorAll<HTMLElement>('*')]
  const releaseOrigins = registerDialogOriginSnapshot(originalNodes, copiedNodes)
  const scrollPositions: Array<{ element: HTMLElement; top: number; left: number }> = []
  // CSS 入场动画由 cloneNode 重新创建；保存捕获时的时间轴，插回页面时暂停在同一帧（包含伪元素）。
  type FrozenCssAnimation = { name: string; pseudo: string; time: CSSNumberish | null }
  const animationFrames = new Map<Element, FrozenCssAnimation[]>()
  const copies = new Map<Element, HTMLElement>(originalNodes.map((node, index) => [node, copiedNodes[index]]))
  for (const animation of typeof source.getAnimations === 'function' ? source.getAnimations({ subtree: true }) : []) {
    if (!('animationName' in animation)) continue
    const effect = animation.effect as KeyframeEffect | null, copied = effect?.target ? copies.get(effect.target) : undefined
    if (!copied) continue
    const frames = animationFrames.get(copied) ?? []
    frames.push({ name: (animation as CSSAnimation).animationName, pseudo: effect?.pseudoElement ?? '', time: animation.currentTime })
    animationFrames.set(copied, frames)
  }
  copiedNodes.forEach((node, index) => {
    const original = originalNodes[index]
    // 离场副本只是一张画面：移除标识和表单归属，不能提交、聚焦或保留第二套可编辑草稿。
    for (const attribute of ['id', 'name', 'for', 'autofocus', 'form', 'aria-labelledby', 'aria-describedby', 'aria-controls']) node.removeAttribute(attribute)
    node.removeAttribute('data-app-modal-id')
    node.tabIndex = -1
    if (node.hasAttribute('contenteditable')) node.contentEditable = 'false'
    // inert 已阻断用户交互；保留原 disabled 状态，避免副本触发禁用样式而在离场或刷新时变灰。
    if (original instanceof HTMLInputElement && node instanceof HTMLInputElement) { node.value = original.value; node.checked = original.checked }
    if (original instanceof HTMLTextAreaElement && node instanceof HTMLTextAreaElement) node.value = original.value
    if (original instanceof HTMLSelectElement && node instanceof HTMLSelectElement) node.selectedIndex = original.selectedIndex
    scrollPositions.push({ element: node, top: original.scrollTop, left: original.scrollLeft })
  })
  clone.inert = true
  clone.setAttribute('aria-hidden', 'true')
  clone.setAttribute('data-dialog-exit-frame', '')
  clone.removeAttribute('role')
  Object.assign(clone.style, { position: 'fixed', left: `${bounds.left}px`, top: `${bounds.top}px`, width: `${bounds.width}px`,
    height: `${bounds.height}px`, maxWidth: 'none', maxHeight: 'none', margin: '0', pointerEvents: 'none', visibility: 'visible', transformOrigin: '0 0' })
  return { element: clone, restoreScroll: () => {
    scrollPositions.forEach(({ element, top, left }) => { element.scrollTop = top; element.scrollLeft = left })
    // 只遍历一次动画列表，避免长表格对每个单元格重复扫描整棵子树。
    const saved = new Map([...animationFrames].map(([node, frames]) => [node, [...frames]]))
    for (const animation of typeof clone.getAnimations === 'function' ? clone.getAnimations({ subtree: true }) : []) {
      if (!('animationName' in animation)) continue
      const effect = animation.effect as KeyframeEffect | null, frames = effect?.target ? saved.get(effect.target) ?? [] : []
      const match = frames.findIndex(frame => frame.name === (animation as CSSAnimation).animationName && frame.pseudo === (effect?.pseudoElement ?? ''))
      if (match >= 0) { animation.pause(); animation.currentTime = frames.splice(match, 1)[0].time ?? 0 }
      else {
        // 原节点已经结束且不保留动画时，副本直接到终点，不能再次播放延迟入场。
        const end = effect?.getComputedTiming().endTime
        if (typeof end === 'number' && Number.isFinite(end)) { animation.pause(); animation.currentTime = end }
        else animation.cancel()
      }
    }
  }, remove: () => { releaseOrigins(); clone.remove() } }
}
