import { findOriginalItem } from './original-items.mjs'
import { sourceDetails, detailSource } from '../../docs/site/source-details.mjs'

// 直接挂载原 App 与原页面；只提供隔离示例桥接，绝不重新排列业务字段。
const surfaces = { receipt:'/workspace/receipts',stock:'/workspace/inventory-ledger',finance:'/workspace/financial-sources' }
const surface = new URLSearchParams(location.search).get('surface')
if (!Object.hasOwn(surfaces,surface)) throw new Error('未知界面预览')
location.hash = surfaces[surface]
const { previewReady } = await import('./main.mjs')
await previewReady
document.getElementById('app').inert = true
let selected = sourceDetails[0], queued = 0

function report() {
  queued = 0
  const node = findOriginalItem(document,surface,selected)
  if (!node) return
  const measured=node.getBoundingClientRect()
  // 原文字周围留一点高亮边距，边框不压住字形；仍以真实 DOM 边界为依据。
  const padding=surface==='receipt'?6:0
  const rect={left:measured.left-padding,top:measured.top-padding,width:measured.width+padding*2,height:measured.height+padding*2}
  parent.postMessage({type:'nexora:preview-row',surface,key:selected.key,sourceId:detailSource(selected),width:innerWidth,height:innerHeight,
    rect:{left:rect.left,top:rect.top,width:rect.width,height:rect.height}},location.origin)
}
const schedule = () => { if (!queued) queued=requestAnimationFrame(report) }
const message = event => {
  if (event.source !== parent || event.origin !== location.origin || event.data?.type !== 'nexora:select-preview-item') return
  const detail=sourceDetails.find(item=>item.key===event.data.key)
  if (detail) {selected=detail;schedule()}
}
window.addEventListener('message',message)
await document.fonts.ready
const observer = new ResizeObserver(schedule)
observer.observe(document.getElementById('app'))
// 表格异步渲染以及字体加载完成后再读取，不靠固定截图像素定位。
const mutations = new MutationObserver(schedule)
mutations.observe(document.getElementById('app'),{childList:true,subtree:true})
schedule()
window.addEventListener('pagehide',()=>{observer.disconnect();mutations.disconnect();window.removeEventListener('message',message);if(queued)cancelAnimationFrame(queued)},{once:true})
