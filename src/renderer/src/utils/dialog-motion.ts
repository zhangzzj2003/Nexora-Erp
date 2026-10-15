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
  let previousWillChange = ''
  function cancel(): void {
    generation++; animation?.cancel(); animation = null
    if (animatedElement) animatedElement.style.willChange = previousWillChange
    animatedElement = null
  }
  function capture(): DialogMotionFrame | null { return animatedElement ? readDialogFrame(animatedElement) : null }
  async function play(element: HTMLElement, from: DialogMotionFrame, to: DialogMotionFrame, duration: number): Promise<boolean> {
    cancel()
    const ticket = generation
    animatedElement = element
    previousWillChange = element.style.willChange
    // 圆角插值会让长表格与大阴影逐帧重绘；先确定外形，时间轴只保留可合成的变换和透明度。
    Object.assign(element.style, from, { borderRadius: to.borderRadius, willChange: 'transform, opacity' })
    if (typeof element.animate !== 'function' || duration === 0) {
      Object.assign(element.style, to); cancel(); return true
    }
    animation = element.animate([
      { transform: from.transform, opacity: from.opacity }, { transform: to.transform, opacity: to.opacity }
    ], { duration, easing: 'cubic-bezier(.22, 1, .36, 1)', fill: 'both' })
    try { await animation.finished } catch { return false }
    if (ticket !== generation) return false
    Object.assign(element.style, to)
    cancel()
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
  const animations = typeof source.getAnimations === 'function' ? source.getAnimations({ subtree: true }) : []
  // 只有正在播放 CSS 动画时才需要节点索引，普通详情无需为每个单元格创建映射。
  const copies = animations.length ? new Map<Element, HTMLElement>(originalNodes.map((node, index) => [node, copiedNodes[index]])) : null
  for (const animation of animations) {
    if (!('animationName' in animation)) continue
    const effect = animation.effect as KeyframeEffect | null, copied = effect?.target ? copies?.get(effect.target) : undefined
    if (!copied) continue
    const frames = animationFrames.get(copied) ?? []
    frames.push({ name: (animation as CSSAnimation).animationName, pseudo: effect?.pseudoElement ?? '', time: animation.currentTime })
    animationFrames.set(copied, frames)
  }
  const attributes = ['id', 'name', 'for', 'autofocus', 'form', 'aria-labelledby', 'aria-describedby', 'aria-controls', 'data-app-modal-id']
  // 浏览器一次筛出需要清理的节点，避免对长表格的每个普通单元格逐个检查九种属性。
  const sanitize = (node: HTMLElement): void => {
    for (const attribute of attributes) {
      if (node.hasAttribute(attribute)) node.removeAttribute(attribute)
    }
    if (node.hasAttribute('contenteditable')) node.contentEditable = 'false'
  }
  sanitize(clone)
  clone.querySelectorAll<HTMLElement>([...attributes.map(attribute => `[${attribute}]`), '[contenteditable]'].join(',')).forEach(sanitize)
  copiedNodes.forEach((node, index) => {
    const original = originalNodes[index]
    // 根节点的 inert 已覆盖整个子树，无需给每个表格单元格新增 tabindex。
    // inert 已阻断用户交互；保留原 disabled 状态，避免副本触发禁用样式而在离场或刷新时变灰。
    if (original instanceof HTMLInputElement && node instanceof HTMLInputElement) { node.value = original.value; node.checked = original.checked }
    if (original instanceof HTMLTextAreaElement && node instanceof HTMLTextAreaElement) node.value = original.value
    if (original instanceof HTMLSelectElement && node instanceof HTMLSelectElement) node.selectedIndex = original.selectedIndex
    const top = original.scrollTop, left = original.scrollLeft
    // 只恢复确实滚动过的容器，避免插入副本后为数千个零偏移单元格反复触发布局。
    if (top || left) scrollPositions.push({ element: node, top, left })
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
