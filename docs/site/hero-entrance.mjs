// CSS 从首帧开始出场，脚本只负责轨道跟随和中断，不等待字体、截图或业务视图。
export function mountHeroEntrance(doc = document, win = window) {
  const hero = doc.querySelector('[data-cover]')
  if (!hero) return () => {}
  const reduced = win.matchMedia('(prefers-reduced-motion: reduce)')
  let frame = 0, settled = false
  const windowEvents = ['scroll', 'wheel', 'touchstart', 'pointerdown', 'resize', 'hashchange', 'pagehide']
  const notify = () => win.dispatchEvent(new win.Event('hero:entrance-frame'))
  // 用户开始阅读或操作就立即交还滚动控制；移除出场动画后仍保留原有透视样式。
  function settle() {
    if (settled) return
    settled = true
    if (frame) win.cancelAnimationFrame(frame)
    frame = 0
    hero.dataset.heroSettled = 'true'
    windowEvents.forEach(name => win.removeEventListener(name, settle))
    hero.removeEventListener('focusin', settle)
    doc.removeEventListener('visibilitychange', settle)
    reduced.removeEventListener('change', settle)
    notify()
  }
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
  // 锚点访问、历史位置恢复、减少动态及后台标签直接呈现最终画面。
  if (reduced.matches || doc.hidden || win.scrollY > 8 || win.location.hash || !hero.getAnimations) {
    settle()
    return settle
  }
  windowEvents.forEach(name => win.addEventListener(name, settle, { passive: true }))
  hero.addEventListener('focusin', settle)
  doc.addEventListener('visibilitychange', settle)
  reduced.addEventListener('change', settle)
  frame = win.requestAnimationFrame(tick)
  return settle
}
