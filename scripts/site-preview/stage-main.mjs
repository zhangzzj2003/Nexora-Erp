import { findOriginalItem } from './original-items.mjs'
import { sourceDetails, detailSource } from '../../docs/site/source-details.mjs'

// 原页面尚未加载时也接收物料选择，避免首次打开或快速切换丢失父页面消息。
const surfaces = { receipt:'/workspace/receipts',stock:'/workspace/inventory-ledger',finance:'/workspace/financial-sources' }
const surface = new URLSearchParams(location.search).get('surface')
if (!Object.hasOwn(surfaces,surface)) throw new Error('未知界面预览')
location.hash = surfaces[surface]
let selected = sourceDetails[0], queued = 0, ready = false
const send = data => parent.postMessage({surface,...data},location.origin)
function report() {
  queued = 0
  if (!ready) return
  const node = findOriginalItem(document,surface,selected)
  if (!node) return
  const measured=node.getBoundingClientRect(),padding=surface==='receipt'?6:0
  // 高亮依旧使用原文字与单元格，边框不压住字形。
  const rect={left:measured.left-padding,top:measured.top-padding,width:measured.width+padding*2,height:measured.height+padding*2}
  send({type:'nexora:preview-row',key:selected.key,sourceId:detailSource(selected),width:innerWidth,height:innerHeight,rect})
}
const schedule = () => { if (ready && !queued) queued=requestAnimationFrame(report) }
const message = event => {
  if (event.source !== parent || event.origin !== location.origin || event.data?.type !== 'nexora:select-preview-item') return
  const detail=sourceDetails.find(item=>item.key===event.data.key)
  // 初次就绪和物料切换立即回报，不依赖隐藏 iframe 中可能被暂停的动画帧。
  if (detail) {selected=detail;report()}
}
window.addEventListener('message',message)
// 让入口模块先完成求值，视图加载不会阻塞文档 load 与父页面的初始化。
async function boot() {
  try {
    const { previewReady } = await import('./main.mjs')
    await previewReady
    const app=document.getElementById('app')
    app.inert = true;ready = true
    send({type:'nexora:preview-ready',width:innerWidth,height:innerHeight})
    report()
    const observer = new ResizeObserver(schedule),mutations = new MutationObserver(schedule)
    observer.observe(app);mutations.observe(app,{childList:true,subtree:true})
    // 先显示原界面；字体完成后只校正位置，不再用字体阻挡整个预览。
    document.fonts.ready.then(schedule)
    window.addEventListener('pagehide',()=>{observer.disconnect();mutations.disconnect();window.removeEventListener('message',message);if(queued)cancelAnimationFrame(queued)},{once:true})
  } catch {
    // 分包丢失等加载错误立即回报，不让用户一直看着加载中。
    send({type:'nexora:preview-error'})
    window.removeEventListener('message',message)
  }
}
void boot()
