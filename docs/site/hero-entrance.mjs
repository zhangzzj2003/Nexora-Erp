// 在 head 中同步执行：先确定首屏状态，避免正文绘制后才从动画切换到静态。
export function preparePageEntry(doc, win) {
  const root = doc.documentElement
  root.dataset.heroEntrance = win.scrollY > 8 || doc.hidden ||
    win.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'static' : 'intro'
  // 首次锚点定位与浏览器位置恢复保持即时；加载后两帧再启用用户点击时的平滑滚动。
  const ready = () => win.requestAnimationFrame(() => win.requestAnimationFrame(() => {
    root.dataset.navigationReady = 'true'
  }))
  if (doc.readyState === 'complete') ready()
  else win.addEventListener('load', ready, { once: true })
}

// 同一函数生成同步启动脚本并用于单元测试，不增加首轮网络请求或依赖模块加载顺序。
export const pageEntryScript = `(${preparePageEntry.toString()})(document,window);`

// CSS 从首帧开始出场，后续模块只负责轨道跟随和中断，不等待字体、截图或业务视图。
export function mountHeroEntrance(doc = document, win = window) {
  const hero = doc.querySelector('[data-cover]')
  if (!hero) return () => {}
  const reduced = win.matchMedia('(prefers-reduced-motion: reduce)')
  let frame = 0, settled = false
  const windowEvents = ['wheel', 'touchstart', 'pointerdown', 'resize', 'hashchange', 'pagehide']
  const notify = () => win.dispatchEvent(new win.Event('hero:entrance-frame'))
  // 用户开始阅读或操作就立即交还滚动控制；移除出场动画后仍保留原有透视样式。
  function settle() {
    if (settled) return
    settled = true
    if (frame) win.cancelAnimationFrame(frame)
    frame = 0
    hero.dataset.heroSettled = 'true'
    windowEvents.forEach(name => win.removeEventListener(name, settle))
    win.removeEventListener('scroll', onScroll)
    hero.removeEventListener('focusin', settle)
    doc.removeEventListener('visibilitychange', settle)
    reduced.removeEventListener('change', settle)
    notify()
  }
  // 浏览器刷新也可能报告一次顶部 scroll；只有实际离开顶部才中断出场。
  function onScroll() { if (win.scrollY > 8) settle() }
  function tick() {
    frame = 0
    if (settled) return
    // 测量由轨道模块统一完成，有限出场结束后不再请求帧，也不会常驻漂浮。
    const running = hero.getAnimations({ subtree: true }).some(animation =>
      animation.animationName?.startsWith('hero-enter-') && animation.playState !== 'finished')
    if (!running) { settle(); return }
    notify()
    frame = win.requestAnimationFrame(tick)
  }
  // 按实际位置判断，保留锚点的顶部刷新也能出场；下方恢复、减少动态和后台直接可读。
  if (doc.documentElement?.dataset.heroEntrance === 'static' || reduced.matches || doc.hidden || win.scrollY > 8 || !hero.getAnimations) {
    settle()
    return settle
  }
  windowEvents.forEach(name => win.addEventListener(name, settle, { passive: true }))
  win.addEventListener('scroll', onScroll, { passive: true })
  hero.addEventListener('focusin', settle)
  doc.addEventListener('visibilitychange', settle)
  reduced.addEventListener('change', settle)
  frame = win.requestAnimationFrame(tick)
  return settle
}
