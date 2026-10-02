// 三个页面使用同一入库的逐行证据；切换物料只换高亮，绝不触发业务写入。
export const sourceDetails = [
  { key: 'mcu', line: 1, sku: 'EL-IC-000001', zh: '低功耗微控制器', en: 'Microcontroller', shortZh: '微控制器', quantity: 200, amount: 4000 },
  { key: 'resistor', line: 2, sku: 'EL-SR-000001', zh: '贴片电阻', en: 'Chip resistor', shortZh: '电阻', quantity: 2000, amount: 400 },
  { key: 'capacitor', line: 3, sku: 'EL-SC-000001', zh: '陶瓷电容', en: 'Ceramic capacitor', shortZh: '电容', quantity: 1000, amount: 400 }
]
// 展示窗口和原页面统一为 3:2，完整状态无需上下补空白。
export const detailCanvas = { width: 720, height: 480 }
// 三窗总览预留字段之间的连线空隙，避免行内锚点落入相邻窗口的重叠区域。
export function detailWindowLayout(layout, reframe = true) {
  const finance = reframe ? Math.max(0, Math.min(1, -(layout[2]?.rotation ?? 0) / 30)) : 0
  const targets = [{x:0,width:.28},{x:.33,width:.34},{x:.73,width:.27}]
  return layout.map((item,index)=>({ ...item, logicalWidth:reframe ? detailCanvas.width : 1000, logicalHeight:reframe ? detailCanvas.height : 1000 * detailCanvas.height / detailCanvas.width,
    rotation:item.rotation*.4, x:item.x+(targets[index].x-item.x)*finance, width:item.width+(targets[index].width-item.width)*finance }))
}
export const detailMoney = amount => `¥${amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

// 镜头从完整页面推进到原字号最高 150%；减少动态和小屏直接呈现可读状态。
export function detailMagnification(progress, focused = false, staticMode = false) {
  if (staticMode || focused) return 1
  const p = Math.max(0, Math.min(1, (progress - .12) / .33))
  return (1 + .5 * p * p * (3 - 2 * p)) / 1.5
}
// 使用未变换的本地布局定位字段，不读取屏幕矩形，避免缩放和透视导致反馈抖动。
export function measureDisplayItem(canvas, detail) {
  if (!canvas || !sourceDetails.includes(detail)) return null
  const nodes = [...canvas.querySelectorAll(`[data-display-item="${detail.key}"]`)]
  if (!nodes.length) return null
  const boxes = nodes.map(node => {
    let left=0,top=0,current=node
    while(current && current!==canvas) {left+=current.offsetLeft;top+=current.offsetTop;current=current.offsetParent}
    return current===canvas ? {left,top,right:left+node.offsetWidth,bottom:top+node.offsetHeight} : null
  })
  if (boxes.some(box=>!box)) return null
  const left=Math.min(...boxes.map(box=>box.left)),top=Math.min(...boxes.map(box=>box.top))
  const rect={left,top,width:Math.max(...boxes.map(box=>box.right))-left,height:Math.max(...boxes.map(box=>box.bottom))-top}
  const width=canvas.offsetWidth,height=canvas.offsetHeight
  if (![width,height,...Object.values(rect)].every(Number.isFinite) || width<=0 || height<=0 || rect.width<=0 || rect.height<=0 || left<0 || top<0 || left+rect.width>width+1 || top+rect.height>height+1) return null
  return {width,height,rect}
}
// 项目风格完整界面与放大区域共用一份 DOM：镜头只平移和缩放，不重排页面。
export function originalCamera(data, width, height, progress, pan = 0) {
  const p=Math.max(0,Math.min(1,progress)),rect=data.rect
  const fit=Math.min(width/data.width,height/data.height)
  // 总览需要看全同一组真实字段；聚焦大窗可接近 150%，不裁掉数量或金额。
  const enlarged=width<=480 ? 1.5 : Math.min(1.5,(width-48)/rect.width)
  const mix=(a,b)=>a+(b-a)*p,scale=mix(fit,enlarged)
  const overflow=Math.max(0,rect.width*enlarged-(width-48))
  const zoomX=width<=480 ? 24-rect.left*enlarged-overflow*Math.max(0,Math.min(1,pan)) : (width-rect.width*enlarged)/2-rect.left*enlarged
  const x=mix((width-data.width*fit)/2,zoomX)
  const y=mix((height-data.height*fit)/2,(height-rect.height*enlarged)/2-rect.top*enlarged)
  const left=Math.max(8,rect.left*scale+x),right=Math.min(width-8,(rect.left+rect.width)*scale+x)
  return {scale,x,y,rect:{left,top:rect.top*scale+y,width:right-left,height:rect.height*scale}}
}
export function detailSource(detail) { return `receipt:101:${detail.line}` }

export function detailControlsMarkup(language) {
  const en = language === 'en'
  return `<div class="detail-controls" role="group" aria-label="${en ? 'Choose a linked material' : '选择关联物料'}"><span>${en ? 'Receipt #101 · Match one item' : '入库 #101 · 逐项对照'}</span>${sourceDetails.map((detail,index)=>`<button type="button" data-source-detail="${detail.key}" aria-pressed="${index===0}">${en ? detail.en : detail.shortZh}</button>`).join('')}</div><p class="detail-summary" data-detail-summary aria-live="polite"></p>`
}

export function mountSourceDetails(scene, language, changed = () => {}, win = window) {
  const buttons = [...scene.querySelectorAll('[data-source-detail]')]
  if (!buttons.length) return Object.assign(() => {},{camera:()=>{}})
  const en = language === 'en', panes = ['receipt','stock','finance'].map(key => scene.querySelector(`[data-detail-key="${key}"]`)).filter(Boolean)
  let selected = sourceDetails[0], cameraProgress = 0
  const select = detail => {
    selected = detail
    buttons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.sourceDetail === detail.key)))
    for (const pane of panes) {
      const key = pane.dataset.detailKey, anchor = pane.querySelector('[data-real-anchor]')
      anchor.dataset.sourceId = detailSource(detail)
      anchor.textContent = `${en ? detail.en : detail.zh} · ${detail.sku} · ${en ? 'Purchase receipt' : '采购入库'} #101`
      pane.querySelector('[data-detail-name]').textContent = en ? detail.en : detail.zh
      pane.querySelector('[data-detail-sku]').textContent = detail.sku
      pane.querySelector('[data-detail-value]').textContent = key === 'finance' ? detailMoney(detail.amount) : `${key === 'stock' ? '+' : ''}${detail.quantity.toLocaleString('en-US')} ${en ? 'units' : '个'}`
    }
    const summary = scene.querySelector('[data-detail-summary]')
    if (summary) summary.textContent = en
      ? `${detail.en} · ${detail.quantity.toLocaleString('en-US')} received → inventory +${detail.quantity.toLocaleString('en-US')} → payable ${detailMoney(detail.amount)}`
      : `${detail.zh} · 入库 ${detail.quantity.toLocaleString('en-US')} 个 → 库存 +${detail.quantity.toLocaleString('en-US')} 个 → 应付 ${detailMoney(detail.amount)}`
    camera(); changed()
  }
  const camera = (value = cameraProgress) => {
    cameraProgress = value
    for (const pane of panes) {
      const canvas = pane.querySelector('[data-display-canvas]')
      const data = measureDisplayItem(canvas,selected)
      // 缺失或越界的字段只隐藏关联边框，界面内容一直保留，不阻挡阅读。
      pane.dataset.previewReady=String(Boolean(data))
      if (!canvas) continue
      const width=pane.clientWidth,height=pane.clientHeight
      const view=data ?? {width:canvas.offsetWidth,height:canvas.offsetHeight,rect:{left:0,top:0,width:canvas.offsetWidth,height:canvas.offsetHeight}}
      if (!width || !height || !view.width || !view.height) continue
      const pose=originalCamera(view,width,height,data ? cameraProgress : 0,Number(pane.dataset.previewPan??0))
      canvas.style.transform=`translate3d(${pose.x}px,${pose.y}px,0) scale(${pose.scale})`
      const rect=pose.rect
      pane.querySelector('[data-real-anchor]').style.cssText=`--item-left:${rect.left/width*100}%;--item-top:${rect.top/height*100}%;--item-width:${rect.width/width*100}%;--item-height:${rect.height/height*100}%`
    }
  }

  const click = event => {
    const button = event.target.closest('[data-source-detail]')
    if (!buttons.includes(button)) return
    const detail = sourceDetails.find(item => item.key === button.dataset.sourceDetail)
    if (detail) select(detail)
  }
  const input = event => {
    const control=event.target.closest('[data-preview-pan]')
    const pane=panes.find(item=>item.dataset.detailKey===control?.dataset.previewPan)
    const value=Number(control?.value)
    if (!pane || !Number.isFinite(value)) return
    pane.dataset.previewPan=String(Math.max(0,Math.min(1,value/100)));camera();changed()
  }
  scene.addEventListener('input',input)
  scene.addEventListener('click',click)
  // 字体与窗口变化只校正同一份 DOM 的锚点，不启动子应用、网络请求或加载计时器。
  const resize=()=>{camera();changed()}
  win.addEventListener('resize',resize)
  select(selected)
  return Object.assign(() => { scene.removeEventListener('click',click);scene.removeEventListener('input',input);win.removeEventListener('resize',resize) },{camera})
}
