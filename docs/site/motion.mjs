import { detailWindowLayout, detailMagnification, mountSourceDetails } from './source-details.mjs'
import { sceneAt, focusLayout, windowGeometry, fitWindowContent, perspective, projectWindowPoint, interpolateWindowPose, connectionEndpoints, sceneBoardHeight, advanceMotionClock } from './scene-geometry.mjs'
export { sceneAt, focusLayout } from './scene-geometry.mjs'
import { mountSandbox } from './sandbox-ui.mjs'
import { createWebGLStage, cubicPoints, pointOnPath } from './webgl-stage.mjs'
import { mountPageOrbit } from './product-orbit.mjs'
import { mountCover } from './cover-motion.mjs'
import { mountHeroEntrance } from './hero-entrance.mjs'

const clamp = value => Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0))
const lerp = (a, b, p) => a + (b - a) * p
const ease = p => 1 - (1 - clamp(p)) ** 3
const keys = ['receipt', 'stock', 'finance']
export const intersectsStage = (rect, stage) => rect.right > stage.left && rect.left < stage.right && rect.bottom > stage.top && rect.top < stage.bottom
export function mountScene(doc = document, win = window) {
  const scene = doc.querySelector('.scroll-scene')
  if (!scene) return () => {}
  const board = scene.querySelector('.scene-board'), windows = keys.map(key => scene.querySelector(`[data-window="${key}"]`))
  const reduced = win.matchMedia('(prefers-reduced-motion: reduce)'), mobile = win.matchMedia('(max-width: 760px), (max-width: 1000px) and (max-height: 619px)'), short = win.matchMedia('(max-height: 619px)')
  const buttons = [...scene.querySelectorAll('[data-stage]')]
  const captions = [...scene.querySelectorAll('[data-caption]')]
  let progress = 0, focused = null, manual = false, frame = 0, onScreen = true, tween = null, disposed = false
  let renderedWindows = sceneAt(0).windows, lastStage = -1, sandbox
  let pendingFocus = null, detailZoom = 2 / 3, detailController
  let graphics
  let resolvedWindows = [], logicalAnchors = [], linksAlpha = 1, heldPose = false
  const realSurface = () => scene.dataset.surface === 'screenshots'
  // 真实明细在独立坐标视窗放大，浅化透视保证行内字段可读；沙盒保持原有布局。
  const surfaceLayout = layout => realSurface() ? detailWindowLayout(layout, !focused) : layout
  const anchorElement = key => board.querySelector(`[${realSurface() ? 'data-real-anchor' : 'data-anchor'}="${key}"]`)
  const staticMode = () => reduced.matches || mobile.matches || short.matches
  const targetProgress = () => {
    const rect = scene.getBoundingClientRect()
    return clamp(-rect.top / Math.max(1, rect.height - win.innerHeight))
  }
  const syncControls = () => {
    scene.dataset.mode = focused ? 'focus' : 'scroll'
  }
  const measureAnchors = () => {
    logicalAnchors = keys.map(key => {
      const element = anchorElement(key)
      if (!element || !element.offsetHeight) return null
      if (realSurface() && element.closest('.real-interface')?.dataset.previewReady !== 'true') return null
      const viewport = element.closest('.window-viewport')
      const local = (node, x, y) => {
        for (let el = node; el && el !== viewport; el = el.offsetParent) { x += el.offsetLeft; y += el.offsetTop }
        return [x, y]
      }
      const edge = key === 'stock' && !realSurface() ? element.closest('tr') : element
      const dot = key === 'receipt' && !realSurface() ? element.querySelector('.anchor-dot') : null
      return { source: realSurface() ? element.dataset.sourceId : element.textContent.trim(), left: local(edge, -5, edge.offsetHeight / 2), right: dot ? local(dot, dot.offsetWidth / 2, dot.offsetHeight / 2) : local(edge, edge.offsetWidth + 4, edge.offsetHeight / 2) }
    })
  }
  const drawLines = () => {
    const root = board.getBoundingClientRect(), state = sceneAt(progress), vertical = staticMode()
    const points = keys.map((key, index) => {
      const anchor = logicalAnchors[index]
      if (!anchor) return null
      if (vertical) {
        const el = anchorElement(key), rect = el.getBoundingClientRect(), edge = key === 'stock' && !realSurface() ? el.closest('tr').getBoundingClientRect() : rect
        return { opacity: 1, source: anchor.source, left: [edge.left - root.left - 5, rect.top + rect.height / 2 - root.top], right: [edge.right - root.left + 4, rect.top + rect.height / 2 - root.top] }
      }
      const item = resolvedWindows[index], project = ([x, y]) => projectWindowPoint(item, x * item.scale, y * (item.scaleY ?? item.scale))
      return { opacity: item.opacity, source: anchor.source, left: project(anchor.left), right: project(anchor.right) }
    })
    const svg = board.querySelector('.connection-layer')
    svg.setAttribute('viewBox', `0 0 ${Math.max(1, root.width)} ${Math.max(1, root.height)}`)
    svg.style.height = `${root.height}px`
    const connections = []
    for (let i = 0; i < 2; i++) {
      const group = svg.querySelector(`[data-connection="${i}"]`), a = points[i], b = points[i + 1]
      const route = connectionEndpoints(a, b, root.width, root.height, vertical)
      const sameSource = a && b && a.source === b.source
      const amount = vertical ? 1 : state.lines[i]
      const alpha = route && sameSource ? linksAlpha : 0
      group.style.opacity = String(alpha * amount)
      if (!route || !sameSource || !alpha) { group.querySelectorAll('path').forEach(path => path.removeAttribute('d')); continue }
      const { start: [x1, y1], end: [x2, y2], bend } = route
      const rail = root.width + 8
      const d = vertical ? `M ${x1} ${y1} C ${rail} ${y1}, ${rail} ${y1}, ${rail} ${y1 + 24} L ${rail} ${y2 - 24} C ${rail} ${y2}, ${rail} ${y2}, ${x2} ${y2}` : `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`
      const curve = vertical
        ? [...cubicPoints([x1, y1], [rail, y1], [rail, y1], [rail, y1 + 24]), ...cubicPoints([rail, y2 - 24], [rail, y2], [rail, y2], [x2, y2])]
        : cubicPoints([x1, y1], [x1 + bend, y1], [x2 - bend, y2], [x2, y2])
      const paths = group.querySelectorAll('path')
      paths.forEach(path => { path.setAttribute('d', d); path.setAttribute('pathLength', '1'); path.style.strokeDasharray = '1'; path.style.strokeDashoffset = String(1 - amount) })
      const node = group.querySelector('circle'), nodeProgress = staticMode() || focused ? 1 : state.nodes[i]
      const pos = pointOnPath(curve, nodeProgress)
      node.setAttribute('cx', String(pos[0])); node.setAttribute('cy', String(pos[1]))
      connections.push({ points: curve, amount, alpha, node: nodeProgress, visible: amount > 0 })
    }
    graphics?.draw({ width: root.width, height: root.height, layout: resolvedWindows, connections, progress, staticMode: staticMode(), ratio: win.devicePixelRatio })
  }
  const stageHeight = layout => {
    const sticky = board.parentElement, style = win.getComputedStyle(sticky)
    const chrome = [...sticky.children].filter(el => el !== board).reduce((sum, el) => {
      const css = win.getComputedStyle(el)
      return sum + el.offsetHeight + (parseFloat(css.marginTop) || 0) + (parseFloat(css.marginBottom) || 0)
    }, (parseFloat(style.paddingTop) || 0) + (parseFloat(style.paddingBottom) || 0))
    // 按真实说明、状态及按钮高度预留空间，临界高度也不裁掉顶部和底部。
    return sceneBoardHeight(board.clientWidth, win.innerHeight, chrome, focused ? 0 : layout[0].compact)
  }
  const configure = layout => windows.forEach((el, index) => {
    const item = layout[index]
    el.style.setProperty('--logical-width', `${item.logicalWidth}px`)
    el.style.setProperty('--logical-height', `${item.logicalHeight}px`)
    el.classList.toggle('is-focused', !staticMode() && focused === keys[index])
    el.classList.toggle('is-compact', !staticMode() && item.compact > .5)
  })
  const measure = source => {
    const layout = surfaceLayout(source)
    configure(layout)
    if (realSurface()) { measureAnchors(); return layout }
    const fitted = layout.map((item, index) => {
      const pane = windows[index].querySelector('[data-content]')
      const bottom = Math.max(0, ...[...pane.children].map(child => child.offsetHeight ? child.offsetTop - pane.offsetTop + child.offsetHeight : 0))
      return fitWindowContent(item, bottom + parseFloat(win.getComputedStyle(pane).paddingBottom))
    })
    configure(fitted)
    measureAnchors()
    return fitted
  }
  const place = () => {
    if (realSurface()) {
      const target = detailMagnification(progress, Boolean(focused), staticMode())
      detailZoom = staticMode() || !focused ? target : Math.abs(target-detailZoom) < .001 ? target : lerp(detailZoom,target,.18)
      // 官网展示保留项目完整布局，仅移动同一界面的镜头；端点使用相同镜头矩阵。
      scene.querySelectorAll('.real-interface').forEach(pane => pane.style.setProperty('--detail-zoom',String(detailZoom)))
      detailController?.camera(Math.max(0,Math.min(1,(detailZoom-2/3)*3)))
      measureAnchors()
      if (focused && Math.abs(target-detailZoom) >= .001) schedule()
    }
    windows.forEach((el, index) => {
      const item = resolvedWindows[index]
      if (staticMode()) { el.style.cssText = ''; el.inert = false; el.removeAttribute('aria-hidden') }
      else {
        el.style.width = `${item.pixelWidth}px`
        el.style.height = `${item.pixelHeight}px`
        el.style.setProperty('--logical-width', `${item.logicalWidth}px`)
        el.style.setProperty('--logical-height', `${item.logicalHeight}px`)
        el.style.setProperty('--ui-scale', String(item.scale))
        el.style.setProperty('--ui-scale-y', String(item.scaleY ?? item.scale))
        el.style.transform = `translate3d(${item.left}px,${item.top}px,0) perspective(${perspective}px) rotateY(${item.rotation}deg)`
        el.style.opacity = String(item.opacity)
        el.style.zIndex = focused === keys[index] ? '3' : '2'
        const hidden = item.opacity < .1 || item.left + item.pixelWidth < 0 || item.left > board.clientWidth || (focused && focused !== keys[index])
        el.inert = Boolean(hidden)
        if (hidden) el.setAttribute('aria-hidden', 'true'); else el.removeAttribute('aria-hidden')
      }
    })
    const stage = focused ? keys.indexOf(focused) : sceneAt(progress).stage
    if (lastStage !== stage) {
      buttons.forEach((button, index) => button.setAttribute('aria-pressed', String(index === stage)))
      captions.forEach((caption, index) => { caption.hidden = index !== stage })
      lastStage = stage
    }
    drawLines()
    if (!staticMode()) {
      const root = board.getBoundingClientRect(), pose = resolvedWindows[0]
      const entry = projectWindowPoint(pose, pose.pixelWidth / 2, 0)
      scene.dispatchEvent(new win.CustomEvent('scene:geometry', { detail: { entry: [root.left + entry[0] + win.scrollX, root.top + entry[1] + win.scrollY], progress, manual } }))
    }
  }
  const apply = source => {
    const layout = surfaceLayout(source)
    board.style.height = staticMode() ? '' : `${stageHeight(layout)}px`
    renderedWindows = staticMode() ? layout : measure(layout)
    if (staticMode()) { configure(layout); measureAnchors() }
    resolvedWindows = renderedWindows.map(item => windowGeometry(item, board.clientWidth, board.clientHeight))
    linksAlpha = 1
    place()
  }
  const finishFocus = () => {
    if (!pendingFocus) return
    const heading = windows[keys.indexOf(pendingFocus)].querySelector('h2')
    heading?.focus({ preventScroll: true })
    pendingFocus = null
  }
  const update = time => {
    frame = 0
    if (disposed || doc.hidden || !onScreen) return
    if (tween) {
      tween.clock = advanceMotionClock(tween.clock, time)
      const elapsed = tween.clock.elapsed, lead = Math.min(80, tween.duration * .2)
      if (elapsed < lead) {
        linksAlpha = tween.fromAlpha * (1 - ease(elapsed / lead))
        place(); schedule(); return
      }
      if (!tween.to) {
        renderedWindows = measure(tween.target)
        tween.to = renderedWindows.map(item => windowGeometry(item, board.clientWidth, tween.toHeight))
      }
      const q = ease((elapsed - lead) / (tween.duration - lead))
      progress = lerp(tween.fromProgress, tween.toProgress, q)
      const height = lerp(tween.fromHeight, tween.toHeight, q)
      board.style.height = `${height}px`
      resolvedWindows = tween.to.map((item, index) => interpolateWindowPose(tween.from[index], item, q, height))
      // 重排发生后再显现来源；不把旧锚点插值成悬空端点。
      linksAlpha = ease((q - .8) / .2)
      place()
      if (q < 1) schedule()
      else { tween = null; finishFocus(); if (!manual) schedule() }
    } else {
      if (!manual && !staticMode()) progress = targetProgress()
      if (heldPose) place()
      else apply(focused ? focusLayout(focused) : sceneAt(progress).windows)
      finishFocus()
    }
  }
  const schedule = () => {
    // 偏好切换会改变舞台高度，旧的交叉观察结果不能阻止下一帧重新布置。
    const rect = scene.getBoundingClientRect()
    onScreen = rect.bottom > 0 && rect.top < win.innerHeight
    if (!frame && !disposed && !doc.hidden && onScreen) frame = win.requestAnimationFrame(update)
  }
  graphics = createWebGLStage(board, schedule)
  const startFlight = (p, duration) => {
    const from = resolvedWindows.map(item => ({ ...item })), fromHeight = board.clientHeight
    const target = focused ? focusLayout(focused) : sceneAt(p).windows
    const toHeight = stageHeight(target)
    tween = { from, target, to: null, fromAlpha: linksAlpha, fromHeight, toHeight, fromProgress: progress, toProgress: p, clock: { elapsed: 0, lastTime: null }, duration }
    heldPose = false
  }
  const move = (p, key = null, duration = 450) => {
    manual = true; focused = key
    pendingFocus = key
    if (!staticMode()) startFlight(p, duration)
    else tween = null
    if (staticMode()) {
      progress = p
      if (key) windows[keys.indexOf(key)].scrollIntoView({ behavior: reduced.matches ? 'instant' : 'smooth', block: 'start' })
    }
    syncControls(); schedule()
  }
  const onClick = event => {
    const surface = event.target.closest('[data-surface-select]')
    if (surface) {
      // 两种展示共享镜头但数据独立，切换不重置已填写的沙盒单据。
      scene.dataset.surface = surface.dataset.surfaceSelect
      scene.querySelectorAll('[data-surface-select]').forEach(button => button.setAttribute('aria-pressed', String(button === surface)))
      tween = null; focused = null; heldPose = false; pendingFocus = null; lastStage = -1
      syncControls(); schedule(); return
    }
    const focus = event.target.closest('[data-focus]')
    if (focus) { move(targetProgress(), focus.dataset.focus); return }
    const stage = event.target.closest('[data-stage]')
    if (stage) { scrollToStage([.1, .45, .8, .92][Number(stage.dataset.stage)]); return }
    if (event.target.closest('[data-overview]')) scrollToStage(.92)
  }
  const onFocus = event => { if (keys.includes(event.detail.key)) move(targetProgress(), event.detail.key) }
  const onInputFocus = event => {
    if (event.target.closest('.sandbox-content') && event.target.matches('input,select,textarea')) {
      manual = true; heldPose = Boolean(tween) || heldPose; tween = null; pendingFocus = null; syncControls()
    }
  }
  const onPreference = () => {
    tween = null; focused = null; manual = false; heldPose = false
    pendingFocus = null
    scene.classList.toggle('motion-enabled', !staticMode())
    scene.classList.toggle('mobile-motion', mobile.matches && !reduced.matches)
    if (staticMode()) {
      progress = 1; board.style.height = ''
      // 偏好改变时即使舞台离屏，也不能把旧透视尺寸和 inert 留在纵向内容中。
      windows.forEach(el => { el.style.cssText = ''; el.inert = false; el.removeAttribute('aria-hidden'); el.classList.remove('is-focused', 'is-compact') })
      board.querySelectorAll('[data-connection]').forEach(group => { group.style.opacity = '0' })
      graphics?.draw({ staticMode: true })
    }
    syncControls(); schedule()
  }
  const onVisibility = () => {
    if (doc.hidden) { if (tween) tween.clock.lastTime = null; if (frame) { win.cancelAnimationFrame(frame); frame = 0 } }
    else schedule()
  }
  const followScroll = () => {
    // 页面滚动永远接管镜头；编辑或聚焦不能锁住滚动进度，也不插入恢复延迟。
    manual = false; focused = null; tween = null; heldPose = false; pendingFocus = null
    syncControls(); schedule()
  }
  const scrollToStage = p => {
    followScroll()
    if (staticMode()) { windows[p < .32 ? 0 : p < .63 ? 1 : 2].scrollIntoView({ behavior: reduced.matches ? 'instant' : 'smooth', block: 'start' }); return }
    const rect = scene.getBoundingClientRect()
    win.scrollTo({ top: win.scrollY + rect.top + clamp(p) * Math.max(1, rect.height - win.innerHeight), behavior: 'smooth' })
  }
  const onScroll = followScroll
  scene.addEventListener('click', onClick)
  scene.addEventListener('sandbox:focus', onFocus)
  const onRender = () => {
    if (tween) startFlight(tween.toProgress, tween.duration)
    else if (heldPose) {
      renderedWindows = measure(renderedWindows)
      resolvedWindows = resolvedWindows.map((pose, index) => ({ ...pose, logicalWidth: renderedWindows[index].logicalWidth, logicalHeight: renderedWindows[index].logicalHeight, scaleY: pose.pixelHeight / renderedWindows[index].logicalHeight }))
    }
    schedule()
  }
  const onDetails = event => {
    onRender()
  }
  const destroyDetails = detailController = mountSourceDetails(scene, doc.documentElement.lang, () => {
    // 展示布局变化只更新锚点，不重新启动镜头补间，避免滚动时反馈抖动。
    measureAnchors(); schedule()
  }, win)
  scene.addEventListener('load', onRender, true); scene.addEventListener('error', onRender, true)
  scene.addEventListener('sandbox:render', onRender)
  scene.addEventListener('toggle', onDetails, true)
  scene.addEventListener('focusin', onInputFocus)
  scene.addEventListener('scroll', schedule, true)
  win.addEventListener('scroll', onScroll, { passive: true })
  const onResize = () => { heldPose = false; if (tween) startFlight(tween.toProgress, tween.duration); schedule() }
  win.addEventListener('resize', onResize)
  doc.addEventListener('visibilitychange', onVisibility)
  reduced.addEventListener('change', onPreference); mobile.addEventListener('change', onPreference); short.addEventListener('change', onPreference)
  const observer = new win.IntersectionObserver(entries => {
    onScreen = entries[0].isIntersecting
    if (!onScreen && tween) tween.clock.lastTime = null
    if (!onScreen && frame) { win.cancelAnimationFrame(frame); frame = 0 }
    schedule()
  })
  observer.observe(scene)
  const reveals = new win.IntersectionObserver(entries => entries.forEach(entry => {
    entry.target.classList.toggle('in-view', entry.isIntersecting)
  }), { threshold: .1 })
  windows.forEach(el => reveals.observe(el))
  scene.classList.add('scene-ready')
  onPreference()
  sandbox = mountSandbox(scene, doc.documentElement.lang)
  return () => {
    disposed = true
    if (frame) win.cancelAnimationFrame(frame)
    observer.disconnect(); reveals.disconnect(); sandbox.destroy(); destroyDetails(); graphics.destroy()
    scene.removeEventListener('click', onClick); scene.removeEventListener('sandbox:focus', onFocus); scene.removeEventListener('sandbox:render', onRender)
    scene.removeEventListener('load', onRender, true); scene.removeEventListener('error', onRender, true)
    scene.removeEventListener('toggle', onDetails, true)
    scene.removeEventListener('focusin', onInputFocus); scene.removeEventListener('scroll', schedule, true)
    win.removeEventListener('scroll', onScroll); win.removeEventListener('resize', onResize); doc.removeEventListener('visibilitychange', onVisibility)
    reduced.removeEventListener('change', onPreference); mobile.removeEventListener('change', onPreference); short.removeEventListener('change', onPreference)
  }
}
if (typeof document !== 'undefined') { if (document.querySelector('.page-orbit')) mountPageOrbit(); else mountCover(); mountHeroEntrance(); mountScene() }
