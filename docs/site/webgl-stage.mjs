// GPU 只负责视觉层；表单、焦点与业务数据始终由原生 HTML 管理。
import { perspective, windowGeometry, projectWindowPoint } from './scene-geometry.mjs'
const clamp = value => Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0))
export function cubicPoints(a, b, c, d, count = 48) {
  return Array.from({ length: count + 1 }, (_, i) => {
    const t = i / count, s = 1 - t
    return [0, 1].map(k => s ** 3 * a[k] + 3 * s * s * t * b[k] + 3 * s * t * t * c[k] + t ** 3 * d[k])
  })
}
export function trimPath(points, progress) {
  if (points.length < 2) return points.map(p => [...p])
  if (progress >= 1) return points.map(p => [...p])
  const lengths = points.slice(1).map((p, i) => Math.hypot(p[0] - points[i][0], p[1] - points[i][1]))
  const target = lengths.reduce((a, b) => a + b, 0) * clamp(progress)
  const result = [[...points[0]]]
  let walked = 0
  for (let i = 0; i < lengths.length; i++) {
    const length = lengths[i]
    if (walked + length >= target) {
      const t = length ? (target - walked) / length : 0
      result.push(points[i].map((v, k) => v + (points[i + 1][k] - v) * t))
      break
    }
    result.push([...points[i + 1]])
    walked += length
  }
  return result
}
export const pointOnPath = (points, progress) => trimPath(points, progress).at(-1)
export function ribbonMesh(points, halfWidth) {
  const vertices = []
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i], dx = b[0] - a[0], dy = b[1] - a[1], length = Math.hypot(dx, dy)
    if (length < .001) continue
    const nx = -dy / length * halfWidth, ny = dx / length * halfWidth
    const corners = [[a[0] + nx, a[1] + ny, 1], [a[0] - nx, a[1] - ny, -1], [b[0] + nx, b[1] + ny, 1], [b[0] - nx, b[1] - ny, -1]]
    for (const index of [0, 1, 2, 2, 1, 3]) vertices.push(...corners[index])
  }
  return new Float32Array(vertices)
}

// 光池跟随实体投影的窗底，不能用未透视的矩形宽度替代接触面。
export function floorLightAt(item, width, height) {
  const g = item.pixelWidth ? item : windowGeometry(item, width, height)
  const left = projectWindowPoint(g, 0, g.pixelHeight), right = projectWindowPoint(g, g.pixelWidth, g.pixelHeight)
  if (![...left, ...right, g.opacity].every(Number.isFinite) || g.opacity < .01 || right[0] <= 0 || left[0] >= width) return null
  const center = (left[0] + right[0]) / 2, bottom = (left[1] + right[1]) / 2, span = right[0] - left[0]
  return { center, bottom, span, opacity: g.opacity, depth: Math.min(128, Math.max(85, span * .18)) }
}

const materialVertex = `
attribute vec3 a_position;
uniform vec2 u_canvas, u_stage;
uniform vec4 u_rect;
uniform float u_rotation, u_perspective;
varying vec2 v_uv;
void main(){
  v_uv = a_position.xy;
  vec3 p = vec3((a_position.xy - vec2(.5,1.)) * u_rect.zw, a_position.z);
  float c = cos(u_rotation), s = sin(u_rotation);
  p = vec3(p.x*c + p.z*s, p.y, -p.x*s + p.z*c);
  float w = 1. - p.z / u_perspective;
  vec2 pixel = u_rect.xy + p.xy/w + vec2(40.);
  vec2 clip = pixel / u_canvas * 2. - 1.;
  gl_Position = vec4(clip.x*w, -clip.y*w, 0., w);
}`
const materialFragment = `
precision mediump float;
varying vec2 v_uv;
uniform vec2 u_size;
uniform float u_opacity, u_kind, u_progress, u_edge;
void main(){
  vec2 q=(v_uv-.5)*2.;
  float sideFade=1.-smoothstep(.78,1.,abs(q.x));
  if(u_kind<2.5){
    float contact=exp(-pow(abs(q.x),8.)*2.4-q.y*q.y*8.);
    gl_FragColor=vec4(.19,.29,.35,contact*sideFade*u_opacity*.32);
  }else if(u_kind<3.5){
    float pool=exp(-pow(abs(q.x),4.)*2.2)*pow(1.-v_uv.y,1.6);
    float grain=.965+.035*cos(v_uv.y*230.+v_uv.x*3.);
    gl_FragColor=vec4(.34,.46,.54,pool*grain*sideFade*smoothstep(0.,.04,v_uv.y)*u_opacity*.48);
  }else{
    float y=v_uv.y, spread=.018+y*.11;
    float sweep=.012*sin(u_progress*6.28318);
    float a=exp(-pow((v_uv.x-u_edge-sweep)/spread,2.));
    float b=exp(-pow((v_uv.x-(1.-u_edge)+sweep)/spread,2.));
    float grazing=exp(-pow((y-.055)*26.,2.))*exp(-pow(abs(q.x),6.)*3.);
    float texture=.94+.06*cos(y*170.+v_uv.x*11.)*cos(v_uv.x*95.);
    float light=((a+b)*exp(-y*3.2)+grazing*.45)*pow(1.-y,1.3)*texture;
    vec3 tint=mix(vec3(.77,.91,.98),vec3(1.,.985,.94),a/(a+b+.001));
    gl_FragColor=vec4(tint,light*sideFade*smoothstep(0.,.025,y)*u_opacity*.85);
  }
}`
const lineVertex = `
attribute vec3 a_position;
uniform vec2 u_canvas;
varying float v_edge;
void main(){v_edge=a_position.z;vec2 p=(a_position.xy+vec2(40.))/u_canvas*2.-1.;gl_Position=vec4(p.x,-p.y,0.,1.);}`
const lineFragment = `
precision mediump float;
varying float v_edge;
uniform vec4 u_color;
void main(){float alpha=1.-smoothstep(.35,1.,abs(v_edge));gl_FragColor=vec4(u_color.rgb,u_color.a*alpha);}`
const discVertex = `
attribute vec3 a_position;
uniform vec2 u_canvas, u_center;
uniform float u_radius;
varying vec2 v_uv;
void main(){v_uv=a_position.xy;vec2 p=(u_center+(v_uv-.5)*u_radius*2.+vec2(40.))/u_canvas*2.-1.;gl_Position=vec4(p.x,-p.y,0.,1.);}`
const discFragment = `
precision mediump float;
varying vec2 v_uv;
uniform float u_opacity;
void main(){float r=length(v_uv-.5)*2.;float ring=1.-smoothstep(.55,.8,r);float core=1.-smoothstep(.25,.45,r);vec3 c=mix(vec3(.01,.67,.58),vec3(.93,1.,.98),core);gl_FragColor=vec4(c,ring*u_opacity);}`
const quad = new Float32Array([0,0,0, 1,0,0, 0,1,0, 0,1,0, 1,0,0, 1,1,0])

function compile(gl, type, source) {
  const shader = gl.createShader(type)
  gl.shaderSource(shader, source); gl.compileShader(shader)
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const message = gl.getShaderInfoLog(shader)
    gl.deleteShader(shader)
    throw new Error(message || 'WebGL shader compilation failed')
  }
  return shader
}
function program(gl, vertex, fragment) {
  const shaders = [], p = gl.createProgram()
  try {
    shaders.push(compile(gl, gl.VERTEX_SHADER, vertex))
    shaders.push(compile(gl, gl.FRAGMENT_SHADER, fragment))
    shaders.forEach(shader => gl.attachShader(p, shader)); gl.linkProgram(p)
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p) || 'WebGL link failed')
    return { value: p, attribute: gl.getAttribLocation(p, 'a_position'), uniforms: new Map() }
  } catch (error) { gl.deleteProgram(p); throw error }
  finally { shaders.forEach(shader => gl.deleteShader(shader)) }
}
function renderer(canvas, material) {
  const gl = canvas.getContext('webgl', { alpha: true, antialias: true, premultipliedAlpha: true, powerPreference: 'low-power' })
  if (!gl) throw new Error('WebGL unavailable')
  let programs = [], buffer
  try {
    programs.push(program(gl, material ? materialVertex : lineVertex, material ? materialFragment : lineFragment))
    if (!material) programs.push(program(gl, discVertex, discFragment))
    buffer = gl.createBuffer()
    gl.enable(gl.BLEND); gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA, gl.ONE, gl.ONE_MINUS_SRC_ALPHA)
  } catch (error) { programs.forEach(p => gl.deleteProgram(p.value)); throw error }
  const use = (index, vertices) => {
    const p = programs[index]
    gl.useProgram(p.value); gl.bindBuffer(gl.ARRAY_BUFFER, buffer)
    gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.DYNAMIC_DRAW)
    gl.enableVertexAttribArray(p.attribute); gl.vertexAttribPointer(p.attribute, 3, gl.FLOAT, false, 0, 0)
    return {
      uniform(name, values) {
        if (!p.uniforms.has(name)) p.uniforms.set(name, gl.getUniformLocation(p.value, name))
        gl[`uniform${values.length}f`](p.uniforms.get(name), ...values)
      },
      draw() { gl.drawArrays(gl.TRIANGLES, 0, vertices.length / 3) }
    }
  }
  return {
    gl, use,
    clear(width, height, ratio) {
      const scale = Math.min(2, Math.max(1, ratio), gl.getParameter(gl.MAX_RENDERBUFFER_SIZE) / Math.max(width, height))
      const w = Math.max(1, Math.round(width * scale)), h = Math.max(1, Math.round(height * scale))
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h }
      canvas.style.width = `${width}px`; canvas.style.height = `${height}px`
      gl.viewport(0, 0, w, h); gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT)
    },
    destroy() { if (buffer) gl.deleteBuffer(buffer); programs.forEach(p => gl.deleteProgram(p.value)); programs = [] }
  }
}

function drawConnections(lines, canvasSize, connections, guide = false) {
  for (const connection of connections) {
    if (!connection.visible) continue
    const opacity = (guide ? 1 : connection.amount) * (connection.alpha ?? 1)
    const points = trimPath(connection.points, connection.amount)
    const profile = guide ? [[3, .035], [1.05, .85]] : [[8, .075], [4, .18], [1.7, .95]]
    for (const [halfWidth, alpha] of profile) {
      const p = lines.use(0, ribbonMesh(points, halfWidth))
      p.uniform('u_canvas', canvasSize); p.uniform('u_color', guide ? [.035, .54, .49, alpha * opacity] : [.015, .71, .61, alpha * opacity]); p.draw()
    }
    const node = pointOnPath(connection.points, Math.min(connection.node, connection.amount))
    // 背景辅轨和已经闭合的收尾不显示端点，GPU 与 SVG 保持相同的单线行进语义。
    if (node && connection.showNode !== false) {
      const p = lines.use(1, quad)
      p.uniform('u_canvas', canvasSize); p.uniform('u_center', node); p.uniform('u_radius', [guide ? 3.5 : 7]); p.uniform('u_opacity', [opacity]); p.draw()
    }
  }
}

// 封面只需要轻细的单条路径，共用业务线的着色器和资源释放规则。
export function createWebGLGuide(host, requestFrame = () => {}) {
  const canvas = host.ownerDocument.createElement('canvas')
  canvas.setAttribute('aria-hidden', 'true'); host.append(canvas)
  let graphics, failed = false, disposed = false
  const ready = value => { host.classList.toggle('gpu-ready', value); canvas.hidden = !value }
  const release = () => { graphics?.destroy(); graphics = undefined }
  const initialize = () => {
    try { release(); graphics = renderer(canvas, false); failed = false; return true }
    catch { release(); failed = true; ready(false); return false }
  }
  const lost = event => { event.preventDefault(); failed = true; ready(false); requestFrame() }
  const restored = () => { if (!disposed && initialize()) requestFrame() }
  canvas.addEventListener('webglcontextlost', lost); canvas.addEventListener('webglcontextrestored', restored)
  ready(false)
  return {
    draw({ width, height, connections = [], ratio = 1, staticMode = false }) {
      if (disposed || failed || staticMode || !connections.some(line => line.visible)) { ready(false); return false }
      if (!graphics && !initialize()) return false
      if (graphics.gl.isContextLost()) { failed = true; ready(false); return false }
      ready(true)
      const size = [width + 80, height + 80]
      graphics.clear(...size, ratio)
      drawConnections(graphics, size, connections, true)
      return true
    },
    destroy() { disposed = true; release(); ready(false); canvas.removeEventListener('webglcontextlost', lost); canvas.removeEventListener('webglcontextrestored', restored); canvas.remove() }
  }
}

// 下层只绘制地面光影，来源线在前方；窗口使用干净的薄边，不叠加镀层。
export function createWebGLStage(board, requestFrame = () => {}) {
  const scene = board.closest('.scroll-scene'), doc = board.ownerDocument
  const canvases = ['webgl-materials', 'webgl-connections'].map(className => {
    const canvas = doc.createElement('canvas')
    canvas.className = className; canvas.setAttribute('aria-hidden', 'true'); board.append(canvas)
    return canvas
  })
  let renderers = [], disposed = false, failed = false
  const setReady = ready => {
    scene.classList.toggle('webgl-ready', ready)
    scene.dataset.renderer = ready ? 'webgl' : 'fallback'
    canvases.forEach(c => { c.hidden = !ready })
  }
  const disposeResources = () => { renderers.forEach(r => r.destroy()); renderers = [] }
  const initialize = () => {
    try {
      disposeResources()
      renderers.push(renderer(canvases[0], true)); renderers.push(renderer(canvases[1], false))
      failed = false; return true
    } catch { disposeResources(); failed = true; setReady(false); return false }
  }
  const onLost = event => { event.preventDefault(); failed = true; setReady(false); requestFrame() }
  const onRestored = () => { if (!disposed && initialize()) requestFrame() }
  canvases.forEach(c => { c.addEventListener('webglcontextlost', onLost); c.addEventListener('webglcontextrestored', onRestored) })
  function draw(frame) {
    if (disposed || failed) return false
    const { width, height, layout, connections, staticMode, ratio = 1, progress = 0 } = frame
    if (staticMode) { setReady(false); return false }
    if (!renderers.length && !initialize()) return false
    if (renderers.some(r => r.gl.isContextLost())) { failed = true; setReady(false); return false }
    setReady(true)
    const canvasSize = [width + 80, height + 140], [surface, lines] = renderers
    renderers.forEach(r => r.clear(...canvasSize, ratio))
    const material = (rect, rotation, opacity, kind) => {
      const p = surface.use(0, quad)
      p.uniform('u_canvas', canvasSize); p.uniform('u_stage', [width, height]); p.uniform('u_rect', rect)
      p.uniform('u_size', rect.slice(2)); p.uniform('u_rotation', [rotation * Math.PI / 180]); p.uniform('u_perspective', [perspective])
      p.uniform('u_opacity', [opacity]); p.uniform('u_kind', [kind]); p.uniform('u_progress', [clamp(progress)]); p.uniform('u_edge', [50 / rect[2]]); p.draw()
    }
    for (const item of layout) {
      if (item.opacity < .01) continue
      const light = floorLightAt(item, width, height)
      if (!light) continue
      const { center, bottom, span, depth, opacity } = light
      // 漫射底色承接低角度掠光，再用短接触阴影把窗口压在地面上；不绘制内容镜像。
      material([center, bottom + depth, span + 100, depth], 0, opacity, 3)
      material([center, bottom + depth - 2, span + 100, depth], 0, opacity, 4)
      material([center, bottom + 14, span + 24, 25], 0, opacity, 2)
    }
    // 三角带代替硬件宽线，保证不同 GPU 的线宽与柔边一致。
    drawConnections(lines, canvasSize, connections)
    return true
  }
  setReady(false)
  return {
    draw,
    destroy() {
      disposed = true; disposeResources(); setReady(false)
      canvases.forEach(c => { c.removeEventListener('webglcontextlost', onLost); c.removeEventListener('webglcontextrestored', onRestored); c.remove() })
    }
  }
}
