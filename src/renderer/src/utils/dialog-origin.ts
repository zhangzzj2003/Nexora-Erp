// 动画来源只由具体打开入口登记，绝不读取全局“最后一次点击”坐标。
export interface DialogRect { left: number; top: number; width: number; height: number }
export interface DialogOrigin { element: Element; rect: DialogRect; borderRadius: string }
const origins = new Map<string, DialogOrigin>()
const originListeners = new Map<string, Set<(origin: DialogOrigin | null) => void>>()
const originSnapshots = new WeakMap<Element, Set<Element>>()
export function registerDialogOriginSnapshot(sources: readonly Element[], copies: readonly Element[]): () => void {
  // 父窗口忙碌时真实入口被隐藏，但只读快照中的对应入口仍可见；只接受一一对应的存活副本。
  sources.forEach((source, index) => {
    const nodes = originSnapshots.get(source) ?? new Set<Element>()
    if (copies[index]) nodes.add(copies[index])
    originSnapshots.set(source, nodes)
  })
  return () => sources.forEach((source, index) => {
    const nodes = originSnapshots.get(source)
    nodes?.delete(copies[index]); if (!nodes?.size) originSnapshots.delete(source)
  })
}
function notifyOrigin(key: string, origin: DialogOrigin | null): void { for (const notify of originListeners.get(key) ?? []) notify(origin) }
export function onDialogOriginCaptured(key: string | undefined, notify: (origin: DialogOrigin | null) => void): () => void {
  if (!key) return () => undefined
  const listeners = originListeners.get(key) ?? new Set<(origin: DialogOrigin | null) => void>()
  listeners.add(notify); originListeners.set(key, listeners)
  return () => { listeners.delete(notify); if (!listeners.size) originListeners.delete(key) }
}

function isElement(value: unknown): value is Element {
  return !!value && typeof (value as Element).getBoundingClientRect === 'function'
}
export function dialogRect(rect: Pick<DOMRectReadOnly, 'left' | 'top' | 'width' | 'height'>): DialogRect {
  return { left: rect.left, top: rect.top, width: rect.width, height: rect.height }
}
export function captureDialogOrigin(key: string, source?: Event | Element | null): DialogOrigin | null {
  const element = isElement(source) ? source : source?.currentTarget
  if (!isElement(element)) { origins.delete(key); notifyOrigin(key, null); return null }
  const origin: DialogOrigin = { element, rect: dialogRect(element.getBoundingClientRect()),
    borderRadius: typeof getComputedStyle === 'function' ? getComputedStyle(element).borderRadius : '12px' }
  origins.set(key, origin); notifyOrigin(key, origin)
  return origin
}
export function getDialogOrigin(key?: string): DialogOrigin | null {
  return key ? origins.get(key) ?? null : null
}
export function releaseDialogOrigin(key: string | undefined, origin: DialogOrigin | null): void {
  // 旧窗口离场不能删除相同入口刚登记的新一轮来源。
  if (key && origins.get(key) === origin) origins.delete(key)
}
export function clearDialogOrigins(): void { origins.clear() }
export function visibleDialogOrigin(origin: DialogOrigin | null, viewport: { width: number; height: number }): DialogRect | null {
  if (!origin) return null
  const direct = visibleElementRect(origin.element, viewport)
  if (direct) return direct
  for (const copy of originSnapshots.get(origin.element) ?? []) {
    const visible = visibleElementRect(copy, viewport)
    if (visible) return visible
  }
  return null
}
function visibleElementRect(element: Element, viewport: { width: number; height: number }): DialogRect | null {
  if (!element.isConnected) return null
  if (typeof getComputedStyle === 'function') {
    const style = getComputedStyle(element)
    if (style.visibility === 'hidden' || style.visibility === 'collapse' || style.display === 'none') return null
  }
  const rect = dialogRect(element.getBoundingClientRect())
  if (![rect.left, rect.top, rect.width, rect.height].every(Number.isFinite)
    || rect.width <= 0 || rect.height <= 0 || rect.left + rect.width <= 0 || rect.top + rect.height <= 0
    || rect.left >= viewport.width || rect.top >= viewport.height) return null
  // 入口可能仍在视口坐标内，却已被表格滚动区裁掉；逐级求真实可见交集。
  let left = Math.max(0, rect.left), top = Math.max(0, rect.top)
  let right = Math.min(viewport.width, rect.left + rect.width), bottom = Math.min(viewport.height, rect.top + rect.height)
  if (typeof getComputedStyle === 'function') {
    for (let parent = element.parentElement; parent; parent = parent.parentElement) {
      const style = getComputedStyle(parent), clipX = /^(auto|scroll|hidden|clip)$/.test(style.overflowX), clipY = /^(auto|scroll|hidden|clip)$/.test(style.overflowY)
      if (!clipX && !clipY) continue
      const box = parent.getBoundingClientRect(), insetX = parent.clientLeft || 0, insetY = parent.clientTop || 0
      if (clipX) { left = Math.max(left, box.left + insetX); right = Math.min(right, box.left + insetX + parent.clientWidth) }
      if (clipY) { top = Math.max(top, box.top + insetY); bottom = Math.min(bottom, box.top + insetY + parent.clientHeight) }
      if (right <= left || bottom <= top) return null
    }
  }
  // 关闭前重测入口，滚动或表格重排后仍返回真正可见的位置。
  return { left, top, width: right - left, height: bottom - top }
}
