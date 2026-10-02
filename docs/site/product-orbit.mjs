import { cubicPoints, pointOnPath, createWebGLGuide } from './webgl-stage.mjs'

// 页面节点使用实测视口坐标，滚动、缩放和字体变化后重新连线，不写入任何业务状态。
export function pageOrbitSegments(nodes, width, height, edgeRail = false) {
  const lines = []
  for (let index = 1; index < nodes.length; index++) {
    const a = nodes[index - 1], b = nodes[index]
    if (![...a, ...b, width, height].every(Number.isFinite) || width <= 0 || height <= 0) continue
    if (Math.max(a[1], b[1]) < -40 || Math.min(a[1], b[1]) > height + 40 || b[1] < a[1] - 40) continue
    const dy = b[1] - a[1]
    // 手机沿 12px 外缘下行，先转出正文区域再接入编号，避免穿过标题。
    const points = edgeRail && dy > 64
      ? [...cubicPoints(a, [a[0], a[1]+16], [12, a[1]+16], [12, a[1]+32], 16), [12,b[1]-24], ...cubicPoints([12,b[1]-24], [12,b[1]-8], [b[0],b[1]-8], b, 16)]
      : cubicPoints(a, [a[0], a[1] + dy * .55], [b[0], b[1] - dy * .55], b)
    lines.push({ points, amount: 1, alpha: .62, node: 1, visible: true })
  }
  return lines
}

// 首屏的椭圆环解释空间轨道；取景图仍使用 HTML，便于阅读、失败提示和键盘放大。
export function orbitRing(center, radius, phase = 0) {
  return Array.from({ length: 97 }, (_, i) => {
    const angle = i / 96 * Math.PI * 2 + phase
    return [center[0] + Math.cos(angle) * radius[0], center[1] + Math.sin(angle) * radius[1] + Math.cos(angle) * radius[0] * .09]
  })
}

export function mountPageOrbit(doc = document, win = window) {
  const host = doc.querySelector('.page-orbit')
  if (!host) return () => {}
  const svg = host.querySelector('svg'), hero = doc.querySelector('[data-cover]')
  const nodes = [...doc.querySelectorAll('[data-orbit-node]')]
  const cards = [...doc.querySelectorAll('[data-orbit-card]')]
  const peeks = [...doc.querySelectorAll('.hero-peek img')]
  // 装饰卫星加载失败时整窗隐藏，避免留下空白的假界面。
  const onImage = event => { event.target.parentElement.hidden = event.type === 'error'; schedule() }
  peeks.forEach(image => { image.addEventListener('load', onImage); image.addEventListener('error', onImage); if (image.complete && !image.naturalWidth) image.parentElement.hidden = true })
  const reduced = win.matchMedia('(prefers-reduced-motion: reduce)')
  const mobile = win.matchMedia('(max-width: 760px)')
  let frame = 0, disposed = false, lastTime = 0
  const graphics = createWebGLGuide(host, schedule)
  function draw(time = 0) {
    frame = 0
    if (disposed || doc.hidden) return
    const staticMode = reduced.matches || mobile.matches
    const coordinates = nodes.filter(node => node.offsetHeight > 0).map(node => {
      const rect = node.getBoundingClientRect()
      // 文档段落沿外缘接续，避免轨道穿过正文或表格。
      return node.dataset.orbitNode === 'edge' ? [Math.max(12, rect.left - 18), rect.top + 24] : [rect.left + rect.width / 2, rect.top + rect.height / 2]
    })
    const lines = pageOrbitSegments(coordinates, win.innerWidth, win.innerHeight, mobile.matches)
    const rect = hero.getBoundingClientRect()
    const heroVisible = rect.bottom > 0 && rect.top < win.innerHeight
    if (!staticMode && heroVisible) {
      const center = [win.innerWidth / 2, rect.top + rect.height * .54]
      lines.push({ points: orbitRing(center, [Math.min(720, win.innerWidth * .48), rect.height * .25]), amount: 1, alpha: .17, node: (time / 24000) % 1, visible: true })
      lines.push({ points: orbitRing(center, [Math.min(590, win.innerWidth * .4), rect.height * .34], .6), amount: 1, alpha: .1, node: (time / 32000 + .45) % 1, visible: true })
    }
    for (const line of lines) if (line.alpha > .2) line.node = staticMode ? 1 : (time / 7000) % 1
    svg.setAttribute('viewBox', `0 0 ${win.innerWidth} ${win.innerHeight}`)
    svg.innerHTML = lines.map(line => {
      const pos = pointOnPath(line.points, line.node)
      return `<path d="${line.points.map(([x,y], i) => `${i ? 'L' : 'M'}${x.toFixed(2)} ${y.toFixed(2)}`).join(' ')}" opacity="${line.alpha}"/><circle cx="${pos[0]}" cy="${pos[1]}" r="3" opacity="${line.alpha}"/>`
    }).join('')
    const gpu = graphics.draw({ width: win.innerWidth, height: win.innerHeight, connections: lines, ratio: win.devicePixelRatio, staticMode })
    host.dataset.renderer = gpu ? 'webgl' : 'fallback'
    host.hidden = lines.length === 0
    for (const [index, card] of cards.entries()) {
      const bounds = card.getBoundingClientRect()
      const progress = Math.max(-1, Math.min(1, (bounds.top + bounds.height / 2 - win.innerHeight / 2) / win.innerHeight))
      card.style.setProperty('--orbit-y', `${staticMode ? 0 : progress * 12}px`)
      card.style.setProperty('--orbit-angle', `${staticMode ? 0 : (index % 2 ? -1 : 1) * Math.abs(progress) * 2.5}deg`)
    }
    // 光点只在展示区慢速流动；后台、减少动态或正文阅读时停止循环。
    const visibleCard = cards.some(card => { const r = card.getBoundingClientRect(); return r.bottom > 0 && r.top < win.innerHeight })
    if (!staticMode && gpu && (heroVisible || visibleCard)) schedule()
    lastTime = time
  }
  function tick(time) {
    if (time - lastTime < 32) { frame = 0; schedule(); return }
    draw(time)
  }
  function schedule() { if (!disposed && !doc.hidden && !frame) frame = win.requestAnimationFrame(tick) }
  function visibility() {
    if (doc.hidden && frame) { win.cancelAnimationFrame(frame); frame = 0 }
    else schedule()
  }
  win.addEventListener('scroll', schedule, { passive: true }); win.addEventListener('resize', schedule)
  doc.addEventListener('visibilitychange', visibility)
  reduced.addEventListener('change', schedule); mobile.addEventListener('change', schedule)
  doc.fonts?.ready.then(schedule)
  schedule()
  return () => {
    disposed = true
    if (frame) win.cancelAnimationFrame(frame)
    win.removeEventListener('scroll', schedule); win.removeEventListener('resize', schedule)
    doc.removeEventListener('visibilitychange', visibility)
    reduced.removeEventListener('change', schedule); mobile.removeEventListener('change', schedule)
    peeks.forEach(image => { image.removeEventListener('load', onImage); image.removeEventListener('error', onImage) })
    cards.forEach(card => { card.style.removeProperty('--orbit-y'); card.style.removeProperty('--orbit-angle') })
    graphics.destroy(); svg.innerHTML = ''; host.hidden = true
  }
}
