// 坐标对应 1800×1200 原始截图；版本校验要求换图时重新核对取景和逐行边界。
// 官网只放大取景，不改图片中的真实业务字段。
export const sourceCrops = {
  receipt: { version: '055c85af0235', highResVersion: 'b56e60f879c7', x: 810, y: 392, width: 640, height: 256, rows: [[840,451,578,38],[840,490,578,38],[840,528,578,40]] },
  stock: { version: 'd10ea5bb7f09', highResVersion: '8a48e62e4d73', x: 782, y: 394, width: 640, height: 256, rows: [[792,449,620,65],[792,514,620,65],[792,579,620,65]] },
  finance: { version: '5e2fa472cc0c', highResVersion: 'd0f59e9120c4', x: 920, y: 330, width: 640, height: 256, rows: [[932,385,500,64],[932,449,500,66],[932,515,500,65]] }
}

// 三个页面使用同一入库的逐行证据；切换物料只换高亮，绝不触发业务写入。
export const sourceDetails = [
  { key: 'mcu', line: 1, sku: 'EL-IC-000001', zh: '低功耗微控制器', en: 'Microcontroller', shortZh: '微控制器', quantity: 200, amount: 4000 },
  { key: 'resistor', line: 2, sku: 'EL-SR-000001', zh: '贴片电阻', en: 'Chip resistor', shortZh: '电阻', quantity: 2000, amount: 400 },
  { key: 'capacitor', line: 3, sku: 'EL-SC-000001', zh: '陶瓷电容', en: 'Ceramic capacitor', shortZh: '电容', quantity: 1000, amount: 400 }
]
export const detailCanvas = { width: 720, height: 480 }
// 三窗总览预留字段之间的连线空隙，避免行内锚点落入相邻窗口的重叠区域。
export function detailWindowLayout(layout, reframe = true) {
  const finance = reframe ? Math.max(0, Math.min(1, -(layout[2]?.rotation ?? 0) / 30)) : 0
  const targets = [{x:0,width:.28},{x:.33,width:.34},{x:.73,width:.27}]
  return layout.map((item,index)=>({ ...item, logicalWidth:detailCanvas.width, logicalHeight:detailCanvas.height,
    rotation:item.rotation*.4, x:item.x+(targets[index].x-item.x)*finance, width:item.width+(targets[index].width-item.width)*finance }))
}
export const detailMoney = amount => `¥${amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

// 高亮边界与连线锚点共用同一个矩形，百分比换算同时适用于透视窗口和手机平面布局。
export function detailTarget(key, detail, mobile = false) {
  const original = sourceCrops[key], crop = detailCrop(key,detail,mobile), index = sourceDetails.indexOf(detail)
  if (!crop || index < 0) return null
  const [x,y,width,height] = original.rows[index]
  const left=mobile?Math.max(x,crop.x+8):x, right=mobile?Math.min(x+width,crop.x+crop.width-8):x+width
  return { left: (left-crop.x)/crop.width*100, top: (y-crop.y)/crop.height*100, width: (right-left)/crop.width*100, height: height/crop.height*100 }
}
// 小屏只放大当前行的关键字段，不把完整桌面表格缩成难以辨认的小字。
export function detailCrop(key, detail, mobile = false) {
  const crop=sourceCrops[key], index=sourceDetails.indexOf(detail)
  if(!crop || index<0) return null
  if(!mobile) return crop
  const [x,width]={receipt:[830,440],stock:[1016,340],finance:[1114,340]}[key]
  const row=crop.rows[index]
  return { x, y:row[1]+row[3]/2-56, width, height:112 }
}
export function detailTargetStyle(key, detail) {
  return [false,true].map(mobile=>{
    const rect=detailTarget(key,detail,mobile)
    return rect?Object.entries(rect).map(([name,value])=>`--${mobile?'mobile-':''}item-${name}:${value}%`).join(';'):''
  }).join(';')
}
export function detailImageStyle(key, detail) {
  return [false,true].map(mobile=>{
    const crop=detailCrop(key,detail,mobile)
    if(!crop) return ''
    const prefix=mobile?'--mobile-detail-':'--detail-'
    return `${prefix}left:${-crop.x/crop.width*100}%;${prefix}top:${-crop.y/crop.height*100}%;${prefix}image-width:${1800/crop.width*100}%;${prefix}aspect:${crop.width}/${crop.height}`
  }).join(';')
}
export function detailSource(detail) { return `receipt:101:${detail.line}` }

export function detailControlsMarkup(language) {
  const en = language === 'en'
  return `<div class="detail-controls" role="group" aria-label="${en ? 'Choose a linked material' : '选择关联物料'}"><span>${en ? 'Receipt #101 · Match one item' : '入库 #101 · 逐项对照'}</span>${sourceDetails.map((detail,index)=>`<button type="button" data-source-detail="${detail.key}" aria-pressed="${index===0}">${en ? detail.en : detail.shortZh}</button>`).join('')}</div><p class="detail-summary" data-detail-summary aria-live="polite"></p>`
}

export function mountSourceDetails(scene, language, changed = () => {}) {
  const buttons = [...scene.querySelectorAll('[data-source-detail]')]
  if (!buttons.length) return () => {}
  const en = language === 'en'
  const select = detail => {
    buttons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.sourceDetail === detail.key)))
    for (const key of Object.keys(sourceCrops)) {
      const pane = scene.querySelector(`[data-detail-key="${key}"]`)
      if (!pane) continue
      pane.querySelector('.real-detail-image').style.cssText = detailImageStyle(key, detail)
      const anchor = pane.querySelector('[data-real-anchor]')
      anchor.style.cssText = detailTargetStyle(key, detail)
      anchor.dataset.sourceId = detailSource(detail)
      // 可访问文本描述的是截图中的同一行，不给图片叠加可编辑控件。
      anchor.textContent = `${en ? detail.en : detail.zh} · ${detail.sku} · ${en ? 'Purchase receipt' : '采购入库'} #101`
      pane.querySelector('[data-detail-name]').textContent = en ? detail.en : detail.zh
      pane.querySelector('[data-detail-sku]').textContent = detail.sku
      pane.querySelector('[data-detail-value]').textContent = key === 'finance' ? detailMoney(detail.amount) : `${key === 'stock' ? '+' : ''}${detail.quantity.toLocaleString('en-US')} ${en ? 'units' : '个'}`
    }
    const summary = scene.querySelector('[data-detail-summary]')
    if (summary) summary.textContent = en
      ? `${detail.en} · ${detail.quantity.toLocaleString('en-US')} received → inventory +${detail.quantity.toLocaleString('en-US')} → payable ${detailMoney(detail.amount)}`
      : `${detail.zh} · 入库 ${detail.quantity.toLocaleString('en-US')} 个 → 库存 +${detail.quantity.toLocaleString('en-US')} 个 → 应付 ${detailMoney(detail.amount)}`
    changed()
  }
  const click = event => {
    const button = event.target.closest('[data-source-detail]')
    if (!buttons.includes(button)) return
    const detail = sourceDetails.find(item => item.key === button.dataset.sourceDetail)
    if (detail) select(detail)
  }
  scene.addEventListener('click', click)
  select(sourceDetails[0])
  return () => scene.removeEventListener('click', click)
}
