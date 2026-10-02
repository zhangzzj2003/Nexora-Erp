import { cubicPoints, trimPath, pointOnPath, createWebGLGuide } from './webgl-stage.mjs'

const clamp = value => Math.max(0, Math.min(1, value))
const smooth = value => { const p = clamp(value); return p * p * (3 - 2 * p) }

// 弯下来的主线与环绕段共享切线，接续处只有一个顶点。
function terminalCurve(a, b, tangent) {
  const dy = b[1] - a[1], reach = Math.min(110, dy * .3)
  return cubicPoints(a, [a[0], a[1] + dy * .5], [b[0] - tangent[0] * reach, b[1] - tangent[1] * reach], b)
}

// 路径只做视口裁剪，控制点来自固定布局；滚动不改变曲线的形状。
export function pageOrbitSegments(nodes, width, height, edgeRail = false, terminalTangent = null) {
  const lines = []
  for (let index = 1; index < nodes.length; index++) {
    const a = nodes[index - 1], b = nodes[index]
    if (![...a, ...b, width, height].every(Number.isFinite) || width <= 0 || height <= 0) continue
    if (Math.max(a[1], b[1]) < -40 || Math.min(a[1], b[1]) > height + 40 || b[1] < a[1] - 40) continue
    const dy = b[1] - a[1]
    const terminal = index === nodes.length - 1 && Array.isArray(terminalTangent) && terminalTangent.length === 2 && terminalTangent.every(Number.isFinite)
    // 手机沿 12px 外缘下行，先转出正文区域再接入编号，避免穿过标题。
    const points = terminal
      // 最后一段沿收尾轨道切线汇入，不能用竖直控制点制造生硬的分叉。
      ? terminalCurve(a, b, terminalTangent)
      : edgeRail && dy > 64
      ? [...cubicPoints(a, [a[0], a[1]+16], [12, a[1]+16], [12, a[1]+32], 16), [12,b[1]-24], ...cubicPoints([12,b[1]-24], [12,b[1]-8], [b[0],b[1]-8], b, 16)]
      : cubicPoints(a, [a[0], a[1] + dy * .55], [b[0], b[1] - dy * .55], b)
    lines.push({ points, amount: 1, alpha: terminal ? .38 : .62, node: 1, visible: true })
  }
  return lines
}

// 按弧长找到视口阅读线的位置，GPU/SVG 共用进度；倒滚沿原路收回，不重新起播。
export function orbitProgress(points, height) {
  if (height <= 0 || !Number.isFinite(height) || points.length < 2 || !points.flat().every(Number.isFinite)) return 0
  const cursor = height * .76
  const lengths = points.slice(1).map((b, i) => Math.hypot(b[0] - points[i][0], b[1] - points[i][1]))
  const total = lengths.reduce((sum, length) => sum + length, 0)
  if (!total) return points[0][1] <= cursor ? 1 : 0
  let travelled = 0
  for (let index = 0; index < lengths.length; index++) {
    const a = points[index], b = points[index + 1]
    if (a[1] >= cursor) return clamp(travelled / total)
    if (b[1] > cursor) return clamp((travelled + lengths[index] * (cursor - a[1]) / (b[1] - a[1])) / total)
    travelled += lengths[index]
  }
  return 1
}

// 姿态完全取决于未变形的 figure：中央留出阅读平台，进出场用平滑曲线消除边界跳变。
export function orbitCardPose(bounds, height, index = 0, mobile = false, reduced = false) {
  const reading = { x: 0, y: 0, angle: 0, roll: 0, scale: 1, opacity: 1, phase: 'reading' }
  if (reduced || ![bounds.top, bounds.height, height].every(Number.isFinite) || height <= 0) return reading
  const position = (bounds.top + bounds.height / 2 - height * .52) / (height * .58 + bounds.height * .25)
  const strength = smooth((Math.abs(position) - .23) / .77)
  if (!strength) return reading
  const entering = position > 0, side = index % 2 ? -1 : 1
  return {
    x: mobile ? 0 : side * strength * 56,
    y: strength * (entering ? (mobile ? 28 : 76) : (mobile ? -18 : -48)),
    angle: mobile ? 0 : side * strength * 10,
    roll: mobile ? 0 : side * strength * 1.6,
    scale: 1 - strength * (mobile ? .035 : .1),
    opacity: 1 - strength * (mobile ? .45 : entering ? .78 : .5),
    phase: strength < .001 ? 'reading' : entering ? 'entering' : 'leaving'
  }
}

export function orbitRing(center, radius, phase = 0) {
  return Array.from({ length: 97 }, (_, i) => {
    const angle = i / 96 * Math.PI * 2 + phase
    return [center[0] + Math.cos(angle) * radius[0], center[1] + Math.sin(angle) * radius[1] + Math.cos(angle) * radius[0] * .09]
  })
}

// 使用未旋转的背景尺寸计算倾斜轨道，限制大屏短轴，避免变成笨重的椭圆框；CSS 与 GPU/SVG 保持相同构图。
export function finaleGeometry(bounds, width, ringBounds = null) {
  const ring = ringBounds ?? {left: width / 2 - Math.min(560, width * .43), top: bounds.top + bounds.height / 2 - Math.min(155,bounds.height * .26), width: Math.min(1120, width * .86), height: Math.min(310,bounds.height * .52)}
  if (![ring.left, ring.top, ring.width, ring.height].every(Number.isFinite) || ring.width <= 0 || ring.height <= 0) return null
  const center = [ring.left + ring.width / 2, ring.top + ring.height / 2]
  const tilt = width <= 760 ? -.07 : -.18, phase = 2.3
  const rotate = ([x,y], angle) => [x * Math.cos(angle) - y * Math.sin(angle), x * Math.sin(angle) + y * Math.cos(angle)]
  const path = (rx, ry, angle) => {
    const points = Array.from({length:129}, (_, index) => {
      const theta = phase - index / 128 * Math.PI * 2
      const [x,y] = rotate([Math.cos(theta)*rx, Math.sin(theta)*ry],angle)
      return [center[0]+x,center[1]+y]
    })
    points[points.length-1] = [...points[0]]
    return points
  }
  const points = path(ring.width / 2, ring.height / 2, tilt)
  const tangent = rotate([Math.sin(phase)*ring.width/2, -Math.cos(phase)*ring.height/2],tilt)
  const length = Math.hypot(...tangent)
  // 手机保持较轻的倾角与完整文字空间；辅轨不承担主线接入，只提供空间层次。
  return {points, secondary:path(ring.width*.46,ring.height*.62,width<=760?.09:.16), entry:points[0], tangent:tangent.map(value=>value/length)}
}

// 下降段和整圈组成同一条路径、同一个弧长进度；不能让圆环从另一个端点独立起播。
export function finaleOrbit(bounds, width, height, reduced = false, ringBounds = null, source = null) {
  if (![bounds.top, bounds.height, width, height].every(Number.isFinite) || bounds.height <= 0 || width <= 0 || height <= 0 || (!source && bounds.top >= height) || bounds.top + bounds.height <= 0) return []
  const geometry = finaleGeometry(bounds,width,ringBounds)
  if (!geometry) return []
  if (source && (source.length !== 2 || !source.every(Number.isFinite) || source[1] > geometry.entry[1])) return []
  const approach = source ? terminalCurve(source,geometry.entry,geometry.tangent) : []
  const points = approach.length ? [...approach,...geometry.points.slice(1)] : geometry.points
  const length = path => path.slice(1).reduce((sum,point,index)=>sum+Math.hypot(point[0]-path[index][0],point[1]-path[index][1]),0)
  const leadFraction = length(approach) / length(points)
  // 圈尚未入屏时也允许正文下方的主线推进；之后沿同一前缀继续绕行，倒滚沿原路回收。
  const progress = reduced ? 1 : Math.max(leadFraction*orbitProgress(approach,height),smooth((height-bounds.top)/Math.min(bounds.height,height)))
  if (!points.some(([,y])=>y>=-40) || !points.some(([,y])=>y<=height+40)) return []
  const ringProgress = clamp((progress-leadFraction)/(1-leadFraction))
  return [
    {points, amount:progress, alpha:.38*smooth(progress*12), node:progress, showNode:progress<1, visible:progress>0},
    // 辅轨只做背景层次，不产生第二个运行端点；主线开始环绕后才渐显。
    {points:geometry.secondary, amount:1, alpha:.12*ringProgress, node:0, showNode:false, visible:ringProgress>0}
  ]
}

export function mountPageOrbit(doc = document, win = window) {
  const host = doc.querySelector('.page-orbit')
  if (!host) return () => {}
  const svg = host.querySelector('svg'), hero = doc.querySelector('[data-cover]'), finale = doc.querySelector('[data-orbit-finale]'), finaleRing = doc.querySelector('[data-finale-ring]')
  const nodes = [...doc.querySelectorAll('[data-orbit-node]')]
  const cards = [...doc.querySelectorAll('[data-orbit-card]')]
  const peeks = [...doc.querySelectorAll('.hero-peek img')]
  // 装饰卫星加载失败时整窗隐藏，避免留下空白的假界面。
  const onImage = event => { event.target.parentElement.hidden = event.type === 'error'; schedule() }
  peeks.forEach(image => { image.addEventListener('load', onImage); image.addEventListener('error', onImage); if (image.complete && !image.naturalWidth) image.parentElement.hidden = true })
  const reduced = win.matchMedia('(prefers-reduced-motion: reduce)')
  const mobile = win.matchMedia('(max-width: 760px)')
  let frame = 0, disposed = false
  const graphics = createWebGLGuide(host, schedule)
  function draw() {
    frame = 0
    if (disposed || doc.hidden) return
    const finaleBounds = finale?.getBoundingClientRect(), ringBounds = finaleRing?.getBoundingClientRect()
    const ending = finaleBounds ? finaleGeometry(finaleBounds,win.innerWidth,ringBounds) : null
    // 一帧先集中测量再写样式；不使用 30fps 节流，避免画布落后于浏览器滚动的正文。
    const visibleNodes = nodes.filter(node => node.offsetHeight > 0)
    const coordinates = visibleNodes.map(node => {
      const rect = node.getBoundingClientRect()
      if (node.dataset.orbitNode === 'finale' && ending) return ending.entry
      if (node.dataset.orbitNode === 'stage') {
        // 舞台标题会 sticky，轨道入口固定在舞台自然位置，不能随吸顶反复弯折。
        const scene = node.closest('.scroll-scene').getBoundingClientRect()
        return [rect.left + rect.width / 2, scene.top + 48]
      }
      return node.dataset.orbitNode === 'edge' ? [Math.max(12, rect.left - 18), rect.top + 24] : [rect.left + rect.width / 2, rect.top + rect.height / 2]
    })
    const poses = cards.map((card, index) => orbitCardPose(card.getBoundingClientRect(), win.innerHeight, index, mobile.matches, reduced.matches))
    const rect = hero?.getBoundingClientRect()
    const continuousEnding = ending && visibleNodes.at(-1)?.dataset.orbitNode === 'finale' && coordinates.length > 1
    const lines = pageOrbitSegments(continuousEnding ? coordinates.slice(0,-1) : coordinates, win.innerWidth, win.innerHeight, mobile.matches)
    for (const line of lines) {
      line.amount = reduced.matches ? 1 : orbitProgress(line.points, win.innerHeight)
      // 刚开始绘制时光点也渐显，避免在阅读线附近突然闪出一个亮点。
      line.alpha *= smooth(line.amount * 12)
      line.node = line.amount
      line.visible = line.amount > 0
    }
    if (!reduced.matches && !mobile.matches && rect && rect.bottom > 0 && rect.top < win.innerHeight) {
      const progress = clamp(-rect.top / Math.max(1, rect.height))
      const center = [win.innerWidth / 2, rect.top + rect.height * .54]
      // 首屏光点也随滚动推进，停止滚动即停止运动，不叠加独立的时间动画。
      lines.push({ points: orbitRing(center, [Math.min(720, win.innerWidth * .48), rect.height * .25]), amount: 1, alpha: .17 * (1-progress), node: .15 + progress * .7, visible: true })
      lines.push({ points: orbitRing(center, [Math.min(590, win.innerWidth * .4), rect.height * .34], .6), amount: 1, alpha: .1 * (1-progress), node: .45 + progress * .5, visible: true })
    }
    // 下降段接近视口时即连续绘制，整条路径离屏或页面进入后台后沿用既有停帧机制。
    if (finale) lines.push(...finaleOrbit(finaleBounds, win.innerWidth, win.innerHeight, reduced.matches, ringBounds, continuousEnding ? coordinates.at(-2) : null))
    svg.setAttribute('viewBox', `0 0 ${win.innerWidth} ${win.innerHeight}`)
    svg.innerHTML = lines.filter(line => line.visible).map(line => {
      const path = trimPath(line.points, line.amount), pos = pointOnPath(line.points, line.node)
      return `<path d="${path.map(([x,y], i) => `${i ? 'L' : 'M'}${x.toFixed(2)} ${y.toFixed(2)}`).join(' ')}" opacity="${line.alpha}"/>${line.showNode === false ? '' : `<circle cx="${pos[0]}" cy="${pos[1]}" r="3" opacity="${line.alpha}"/>`}`
    }).join('')
    const gpu = graphics.draw({ width: win.innerWidth, height: win.innerHeight, connections: lines, ratio: win.devicePixelRatio, staticMode: reduced.matches || mobile.matches })
    host.dataset.renderer = gpu ? 'webgl' : 'fallback'
    // SVG 同样可绘制收尾；关闭脚本时由 CSS 静态椭圆兜底。
    if (finale) finale.dataset.orbitReady = 'true'
    host.hidden = !lines.some(line => line.visible)
    cards.forEach((card, index) => {
      const pose = poses[index]
      for (const key of ['x', 'y', 'angle', 'roll', 'scale', 'opacity']) {
        const unit = ['x', 'y'].includes(key) ? 'px' : ['angle', 'roll'].includes(key) ? 'deg' : ''
        card.style.setProperty(`--orbit-${key}`, `${pose[key]}${unit}`)
      }
      card.dataset.orbitPhase = pose.phase
    })
  }
  // 原生滚动只合并到下一帧，不追赶旧坐标、补间或循环；快速跳转直接呈现对应位置。
  function schedule() { if (!disposed && !doc.hidden && !frame) frame = win.requestAnimationFrame(draw) }
  function visibility() {
    if (doc.hidden && frame) { win.cancelAnimationFrame(frame); frame = 0 }
    else schedule()
  }
  win.addEventListener('scroll', schedule, { passive: true }); win.addEventListener('resize', schedule)
  // 首屏卫星的有限出场改变节点坐标，与滚动使用同一个下一帧测量入口。
  win.addEventListener('hero:entrance-frame', schedule)
  doc.addEventListener('visibilitychange', visibility)
  reduced.addEventListener('change', schedule); mobile.addEventListener('change', schedule)
  doc.fonts?.ready.then(schedule)
  schedule()
  return () => {
    disposed = true
    if (frame) win.cancelAnimationFrame(frame)
    win.removeEventListener('scroll', schedule); win.removeEventListener('resize', schedule)
    win.removeEventListener('hero:entrance-frame', schedule)
    doc.removeEventListener('visibilitychange', visibility)
    reduced.removeEventListener('change', schedule); mobile.removeEventListener('change', schedule)
    peeks.forEach(image => { image.removeEventListener('load', onImage); image.removeEventListener('error', onImage) })
    cards.forEach(card => {
      for (const key of ['x', 'y', 'angle', 'roll', 'scale', 'opacity']) card.style.removeProperty(`--orbit-${key}`)
      delete card.dataset.orbitPhase
    })
    if (finale) delete finale.dataset.orbitReady
    graphics.destroy(); svg.innerHTML = ''; host.hidden = true
  }
}
