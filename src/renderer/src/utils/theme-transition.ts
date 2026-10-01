// 圆形过渡由 Pinia 持有；明暗两个方向都从触发按钮展开新主题。
export interface ThemeOrigin { x: number; y: number }
type SnapshotTransition = Pick<ViewTransition, 'ready' | 'finished' | 'skipTransition'>
type SnapshotAnimation = Pick<Animation, 'finished' | 'cancel'>
export interface ThemeTransitionEnvironment {
  width: number
  height: number
  reducedMotion: boolean
  root: {
    dataset: DOMStringMap
    animate: (frames: Keyframe[] | PropertyIndexedKeyframes, options: KeyframeAnimationOptions) => SnapshotAnimation
  }
  start?: (update: () => Promise<void>) => SnapshotTransition
}

export function themeCircleFrames(origin: ThemeOrigin, width: number, height: number): string[] {
  // 高分屏上快照的合成裁剪可能把 px 当作物理像素，导致圆心、半径缩小，
  // 而暂停动画截图又显示正常；统一用百分比，让浏览器按快照自身尺寸换算。
  const center = `${origin.x / width * 100}% ${origin.y / height * 100}%`
  // CSS circle 的百分比半径以「对角线 / √2」为基准，并非宽度或高度。
  // 多覆盖一个 CSS 像素，确保最远角的抗锯齿边缘也展开完毕后才释放快照。
  const radius = Math.hypot(Math.max(origin.x, width - origin.x), Math.max(origin.y, height - origin.y)) + 1
  const radiusPercent = radius / (Math.hypot(width, height) / Math.SQRT2) * 100
  return [`circle(0% at ${center})`, `circle(${radiusPercent}% at ${center})`]
}

export function themeToggleOrigin(event: Pick<MouseEvent, 'clientX' | 'clientY' | 'detail'>,
  rect: Pick<DOMRect, 'left' | 'top' | 'width' | 'height'>): ThemeOrigin {
  // 键盘点击没有鼠标坐标，使用触发按钮中心，避免动画从窗口左上角开始。
  const inside = Number.isFinite(event.clientX) && Number.isFinite(event.clientY)
    && event.clientX >= rect.left && event.clientX <= rect.left + rect.width
    && event.clientY >= rect.top && event.clientY <= rect.top + rect.height
  return event.detail === 0 || !inside
    ? { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 }
    : { x: event.clientX, y: event.clientY }
}

export function createThemeTransition(options: {
  isDark: () => boolean
  setDark: (dark: boolean) => void
  flush: () => Promise<void>
  environment: () => ThemeTransitionEnvironment | undefined
  timeoutMs?: number
}): { toggle: (origin?: ThemeOrigin) => Promise<void>; dispose: () => void } {
  let queue = Promise.resolve()
  let request = 0
  let pending = 0
  let desired = options.isDark()
  let active: SnapshotTransition | undefined
  let animation: SnapshotAnimation | undefined
  let activeRoot: ThemeTransitionEnvironment['root'] | undefined
  let disposed = false

  function stop(): void {
    active?.skipTransition()
    animation?.cancel()
  }

  async function run(dark: boolean, origin: ThemeOrigin | undefined, id: number): Promise<void> {
    if (disposed || id !== request || dark === options.isDark()) return
    const env = options.environment()
    if (!env?.start || env.reducedMotion) {
      options.setDark(dark)
      await options.flush()
      return
    }

    let applied = false
    let ended = false
    const apply = async (): Promise<void> => {
      // 被后续点击替代的快照回调不得迟到覆盖最新主题；降级提交也只执行一次。
      if (applied || disposed || id !== request) return
      applied = true
      options.setDark(dark)
      await options.flush()
    }
    activeRoot = env.root
    env.root.dataset.themeTransition = 'circle'
    let timer: ReturnType<typeof setTimeout> | undefined
    try {
      active = env.start(apply)
      const transition = active
      // 浏览器取消快照时 finished 也可能拒绝，提前订阅避免未处理的 Promise。
      void transition.finished.catch(() => {})
      const effect = async (): Promise<void> => {
        await transition.ready
        if (ended || disposed || id !== request) return
        animation = env.root.animate({
          clipPath: themeCircleFrames(origin ?? { x: env.width / 2, y: env.height / 2 }, env.width, env.height)
        }, {
          duration: 450, easing: 'ease-in', fill: 'forwards',
          pseudoElement: '::view-transition-new(root)'
        })
        await animation.finished
        transition.skipTransition()
        await transition.finished
      }
      // 隐藏窗口、截图失败或动画挂起时及时结束遮罩，主题仍能正常切换。
      await Promise.race([effect(), new Promise<void>(resolve => {
        timer = setTimeout(resolve, options.timeoutMs ?? 2000)
      })])
    } catch {
      // 快照不可用或被连续点击取消时，降级为既有主题更新。
    } finally {
      // 超时后的 ready 仍可能到达，禁止它重新创建已经释放的动画。
      ended = true
      if (timer) clearTimeout(timer)
      stop()
      try {
        await apply()
      } finally {
        // 即使 Vue 更新失败，也必须释放临时样式与快照引用。
        delete env.root.dataset.themeTransition
        active = undefined
        animation = undefined
        activeRoot = undefined
      }
    }
  }

  function toggle(origin?: ThemeOrigin): Promise<void> {
    if (disposed) return Promise.resolve()
    if (pending === 0) desired = options.isDark()
    desired = !desired
    const dark = desired
    const id = ++request
    pending += 1
    stop()
    // 快速点击只执行最后的意图，但保留点击次数的奇偶结果，避免积压整段动画。
    const result = queue.then(() => run(dark, origin, id))
    queue = result.catch(() => {})
    return result.finally(() => { pending -= 1 })
  }

  function dispose(): void {
    disposed = true
    request += 1
    stop()
    if (activeRoot) delete activeRoot.dataset.themeTransition
  }
  return { toggle, dispose }
}
