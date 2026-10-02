import { cubicPoints, trimPath, pointOnPath, createWebGLGuide } from './webgl-stage.mjs'
import { sceneAt, windowGeometry, projectWindowPoint } from './scene-geometry.mjs'

const clamp = value => Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0))
const ease = value => 1 - (1 - clamp(value)) ** 3

// 封面路径不依赖业务数据；固定页面坐标在滚动时统一换算到视口。
export function coverGuideAt({ origin, entry, coverProgress, sceneProgress = 0, manual = false, staticMode = false, width, height }) {
  if (manual || staticMode || !origin || !entry || ![...origin, ...entry, width, height].every(Number.isFinite)) return null
  if (width <= 0 || height <= 0 || entry[1] <= origin[1] || entry[1] < 0 || sceneProgress >= .22) return null
  const length = entry[1] - origin[1], bend = Math.min(72, width * .06, length * .14)
  const points = cubicPoints(origin, [origin[0] + bend, origin[1] + length * .38], [entry[0] - bend, entry[1] - length * .38], entry)
  const amount = .065 + .935 * ease((coverProgress - .02) / .78)
  return { points, amount, node: amount, alpha: 1 - ease((sceneProgress - .08) / .14), visible: true }
}

export function mountCover(doc = document, win = window) {
  const hero = doc.querySelector('[data-cover]'), scene = doc.querySelector('.scroll-scene')
  const showcase = doc.querySelector('#product-preview')
  if (!hero || !scene) return () => {}
  const content = hero.querySelector('.cover-content'), origin = hero.querySelector('.guide-origin'), host = hero.querySelector('.cover-guide'), hint = hero.querySelector('.cover-scroll')
  const svg = host.querySelector('svg'), path = svg.querySelector('path'), tip = svg.querySelector('circle'), board = scene.querySelector('.scene-board')
  const reduced = win.matchMedia('(prefers-reduced-motion: reduce)')
  const short = win.matchMedia('(max-height: 619px)'), mobile = win.matchMedia('(max-width: 760px), (max-width: 1000px) and (max-height: 619px)')
  let frame = 0, disposed = false, pose = null
  const graphics = createWebGLGuide(host, schedule)
  function update() {
    frame = 0
    if (disposed || doc.hidden) return
    const header = doc.querySelector('.site-header')
    hero.style.setProperty('--header-height', `${header.offsetHeight}px`)
    const rect = hero.getBoundingClientRect(), p = clamp(-rect.top / rect.height)
    const active = !reduced.matches && !short.matches, vertical = mobile.matches
    hero.classList.toggle('cover-motion', active)
    content.style.setProperty('--cover-y', `${active ? -28 * ease(p) : 0}px`)
    content.style.setProperty('--cover-scale', String(active ? 1 - .018 * ease(p) : 1))
    hint.style.opacity = String(active ? 1 - ease(p / .15) : 1)
    hint.inert = active && p > .12
    if (hint.inert) hint.setAttribute('aria-hidden', 'true'); else hint.removeAttribute('aria-hidden')
    const start = origin.getBoundingClientRect(), root = board.getBoundingClientRect()
    // 舞台尚未进入视口时按同一套初始几何预测；进入后使用舞台发布的实测投影。
    const initial = windowGeometry(sceneAt(0).windows[0], root.width, root.height)
    const initialPoint = projectWindowPoint(initial, initial.pixelWidth / 2, 0)
    const receipt = scene.querySelector('[data-window="receipt"]').getBoundingClientRect(), sceneRect = scene.getBoundingClientRect()
    // 新增界面区后，封面线止于其开头，避免跨越整组截图连向远处的业务舞台。
    const previewRect = showcase?.getBoundingClientRect()
    const entry = previewRect ? [previewRect.left + previewRect.width / 2, previewRect.top + 24] : vertical ? [(receipt.left + receipt.right) / 2, receipt.top] : pose ? [pose.entry[0] - win.scrollX, pose.entry[1] - win.scrollY] : [root.left + initialPoint[0], root.top + initialPoint[1]]
    const sceneProgress = previewRect ? clamp(-previewRect.top / win.innerHeight) : vertical ? clamp(-sceneRect.top / win.innerHeight) : pose?.progress ?? 0
    const line = coverGuideAt({ origin: [start.left + start.width / 2, start.top + start.height / 2], entry, coverProgress: p, sceneProgress, manual: previewRect || vertical ? false : pose?.manual ?? false, staticMode: !active, width: win.innerWidth, height: win.innerHeight })
    host.hidden = !line
    if (line) {
      const visible = trimPath(line.points, line.amount), head = pointOnPath(line.points, line.amount)
      svg.setAttribute('viewBox', `0 0 ${win.innerWidth} ${win.innerHeight}`)
      path.setAttribute('d', visible.map(([x, y], i) => `${i ? 'L' : 'M'} ${x} ${y}`).join(' '))
      tip.setAttribute('cx', String(head[0])); tip.setAttribute('cy', String(head[1]))
      host.style.opacity = String(line.alpha)
    } else { path.removeAttribute('d'); host.style.opacity = '0' }
    graphics.draw({ width: win.innerWidth, height: win.innerHeight, connections: line ? [line] : [], ratio: win.devicePixelRatio, staticMode: !active || vertical })
  }
  function schedule() {
    if (disposed || doc.hidden || frame) return
    const heroRect = hero.getBoundingClientRect(), sceneRect = scene.getBoundingClientRect()
    // 快速跳出展示区也要清掉上一帧的固定路径，不能把旧线留在文档上方。
    if (host.hidden && heroRect.bottom < -win.innerHeight && (sceneRect.top < -win.innerHeight || sceneRect.top > win.innerHeight)) return
    frame = win.requestAnimationFrame(update)
  }
  const onPose = event => { pose = event.detail; schedule() }
  const onResize = () => { pose = null; schedule() }
  const onVisibility = () => { if (doc.hidden && frame) { win.cancelAnimationFrame(frame); frame = 0 } else schedule() }
  scene.addEventListener('scene:geometry', onPose)
  win.addEventListener('scroll', schedule, { passive: true }); win.addEventListener('resize', onResize)
  doc.addEventListener('visibilitychange', onVisibility)
  for (const media of [reduced, mobile, short]) media.addEventListener('change', onResize)
  doc.fonts?.ready.then(schedule)
  schedule()
  return () => {
    disposed = true; if (frame) win.cancelAnimationFrame(frame)
    scene.removeEventListener('scene:geometry', onPose)
    win.removeEventListener('scroll', schedule); win.removeEventListener('resize', onResize)
    doc.removeEventListener('visibilitychange', onVisibility)
    for (const media of [reduced, mobile, short]) media.removeEventListener('change', onResize)
    graphics.destroy(); hero.classList.remove('cover-motion'); content.style.removeProperty('--cover-y'); content.style.removeProperty('--cover-scale'); host.hidden = true
    hint.style.opacity = ''; hint.inert = false; hint.removeAttribute('aria-hidden')
  }
}
