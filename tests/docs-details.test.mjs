import { test } from 'node:test'
import assert from 'node:assert/strict'
import { sourceDetails, originalCamera, validPreviewRow, detailMagnification, detailSource, detailCanvas, detailWindowLayout, mountSourceDetails } from '../docs/site/source-details.mjs'
import { receipts, ledger, receivablesPayables } from '../scripts/site-preview/fixtures.mjs'
import { sceneAt, windowGeometry, projectWindowPoint, connectionEndpoints } from '../docs/site/scene-geometry.mjs'
import { findOriginalItem } from '../scripts/site-preview/original-items.mjs'

// 对照真实预览数据，验证逐项关联，而不是只检查三个标签同写了 #101。
test('三种物料逐行对应入库、库存及应付证据，金额独立且合计 4800', () => {
  for (const detail of sourceDetails) {
    const receipt=receipts[0].lines.find(line=>line.id===detail.line)
    const movement=ledger.rows.find(row=>row.id===detail.line)
    const finance=receivablesPayables.entries.find(entry=>entry.key===detailSource(detail))
    assert.equal(receipt.sku,detail.sku);assert.equal(Number(receipt.quantity),detail.quantity)
    assert.equal(movement.sku,detail.sku);assert.equal(Number(movement.quantity),detail.quantity)
    assert.equal(finance.sku,detail.sku);assert.equal(Number(finance.amount),detail.amount)
    assert.equal(Number(receipt.unit_price)*detail.quantity,detail.amount)
  }
  assert.equal(sourceDetails.reduce((sum,detail)=>sum+detail.amount,0),4800)
})

// 直接定位原页面单元格，不能把样式和数据拆开重做为另一种表格。
test('原页面明细定位保留真实布局与字段，未知物料不关联',()=>{
  const detail=sourceDetails[0],span={textContent:detail.zh},cells=Array.from({length:7},(_,index)=>({getBoundingClientRect:()=>({left:100*index,top:100,right:100*(index+1),bottom:150})}))
  const row={textContent:detail.sku+' · 采购入库 #101',querySelectorAll:()=>cells}
  const root={querySelectorAll:()=>[span],querySelector:()=>({querySelectorAll:()=>[row]})}
  assert.equal(findOriginalItem(root,'receipt',detail),span)
  assert.deepEqual(findOriginalItem(root,'stock',detail).getBoundingClientRect(),{left:200,top:100,width:300,height:50})
  assert.deepEqual(findOriginalItem(root,'finance',detail).getBoundingClientRect(),{left:300,top:100,width:300,height:50})
  assert.equal(findOriginalItem(root,'stock',sourceDetails[1]),null)
})
test('镜头完整状态保留整页，放大只改变原 DOM 变换，锚点共用同一矩阵',()=>{
  const data={width:1800,height:1200,rect:{left:810,top:450,width:580,height:40}}
  const full=originalCamera(data,720,480,0),zoom=originalCamera(data,1000,1000*2/3,1),middle=originalCamera(data,720,480,.5)
  assert.equal(full.scale,.4);assert.equal(full.x,0);assert.equal(full.y,0)
  assert.equal(zoom.scale,1.5);assert.ok(Math.abs(zoom.rect.top+zoom.rect.height/2-1000/3)<1e-10)
  assert.ok(middle.scale>full.scale);assert.ok(middle.scale<zoom.scale)
  assert.equal(middle.rect.left,data.rect.left*middle.scale+middle.x)
  assert.deepEqual(originalCamera(data,720,480,.5),middle)
})
// 全貌和聚焦窗口的初始镜头都必须贴边，不能以裁切原页面来消除留白。
test('原页面等比例铺满普通及聚焦窗口，没有上下留白且不裁导航或底栏',()=>{
  const data={width:1800,height:1200,rect:{left:810,top:450,width:580,height:40}}
  for(const focused of [false,true]){
    const layout=detailWindowLayout(sceneAt(.1).windows,!focused)
    for(const item of layout){
      const pose=originalCamera(data,item.logicalWidth,item.logicalHeight,0)
      assert.ok(Math.abs(pose.x)<1e-10);assert.ok(Math.abs(pose.y)<1e-10)
      assert.ok(Math.abs(data.width*pose.scale-item.logicalWidth)<1e-10)
      assert.ok(Math.abs(data.height*pose.scale-item.logicalHeight)<1e-10)
    }
  }
})
// 手机保持原字号放大，通过镜头平移查看远处字段，避免整页缩小后难以阅读。
test('手机镜头保留 150% 字号，横向移动可查看末端字段且高亮不越界',()=>{
  const data={width:1800,height:1200,rect:{left:810,top:450,width:580,height:40}}
  const start=originalCamera(data,360,600,1,0),end=originalCamera(data,360,600,1,1)
  assert.equal(start.scale,1.5);assert.equal(end.scale,1.5)
  assert.equal(end.x-start.x,-558)
  assert.equal(data.rect.left*end.scale+end.x+data.rect.width*end.scale,336)
  for(const pose of [start,end]){assert.ok(pose.rect.left>=8);assert.ok(pose.rect.left+pose.rect.width<=352)}
})
test('同一组件放大曲线可倒滚，静态直接可读；三窗实际行边界保留连线间隙', () => {
  assert.equal(detailMagnification(0),2/3); assert.equal(detailMagnification(.45),1)
  assert.equal(detailMagnification(0,true),1); assert.equal(detailMagnification(0,false,true),1)
  let prior=2/3
  for(let p=0;p<=.45;p+=.01){ const next=detailMagnification(p); assert.ok(next>=prior); assert.ok(next-prior<.016); prior=next }
  assert.deepEqual(detailCanvas,{width:720,height:480})
  // 真实共享表格行取景约占视口 6%–94%，不再使用原截图的像素边界。
  for(const width of [1200,1440,1680]) for(const p of [.8,.92]) {
    const poses=detailWindowLayout(sceneAt(p).windows).map(item=>windowGeometry(item,width,520))
    const anchors=poses.map(pose=>({opacity:pose.opacity,left:projectWindowPoint(pose,40*pose.scale,300*pose.scale),right:projectWindowPoint(pose,680*pose.scale,300*pose.scale)}))
    assert.ok(connectionEndpoints(anchors[0],anchors[1],width,520))
    assert.ok(connectionEndpoints(anchors[1],anchors[2],width,520))
  }
})

function detailFixture() {
  const scene=new EventTarget(), win=new EventTarget(), fields=()=>({textContent:''}), timerCallbacks=new Map()
  let timerId=0
  Object.assign(win,{location:{origin:'https://preview.test'},setTimeout(callback){timerCallbacks.set(++timerId,callback);return timerId},clearTimeout(id){timerCallbacks.delete(id)}})
  const buttons=sourceDetails.map(detail=>({dataset:{sourceDetail:detail.key},setAttribute(name,value){this[name]=value}}))
  const panes=Object.fromEntries(['receipt','stock','finance'].map(key=>{
    const anchor={style:{},dataset:{}},name=fields(),sku=fields(),value=fields(),error={hidden:true},sent=[]
    const frame=Object.assign(new EventTarget(),{style:{},contentWindow:{postMessage(data,origin){sent.push({data,origin})}}})
    const pane={clientWidth:720,clientHeight:600,dataset:{detailKey:key},querySelector:selector=>({'iframe':frame,'[data-preview-error]':error,'[data-real-anchor]':anchor,'[data-detail-name]':name,'[data-detail-sku]':sku,'[data-detail-value]':value})[selector]}
    return [key,{...pane,anchor,name,sku,value,frame,error,sent}]
  }))
  const summary=fields();let changes=0
  scene.querySelectorAll=()=>buttons
  scene.querySelector=selector=>selector==='[data-detail-summary]'?summary:panes[selector.match(/"([a-z]+)"/)?.[1]]
  const click=button=>{const event=new Event('click');Object.defineProperty(event,'target',{value:{closest:()=>button}});scene.dispatchEvent(event)}
  const payload=(surface,detail=sourceDetails[0])=>({type:'nexora:preview-row',surface,key:detail.key,sourceId:detailSource(detail),width:720,height:600,rect:{left:40,top:240+60*detail.line,width:640,height:56}})
  const message=(surface,data=payload(surface),origin=win.location.origin,source=panes[surface].frame.contentWindow)=>win.dispatchEvent(Object.assign(new Event('message'),{data,origin,source}))
  return {scene,win,panes,buttons,summary,click,payload,message,timerCallbacks,changed:()=>{changes++},changes:()=>changes}
}
test('同源真实行布局才能显示连线，拒绝跨源、旧选择、越界与无效矩形，卸载清理',()=>{
  const f=detailFixture(),destroy=mountSourceDetails(f.scene,'zh-CN',f.changed,f.win)
  assert.equal(f.panes.stock.dataset.previewReady,'false')
  const initial=f.changes()
  f.message('stock',f.payload('stock'),'https://foreign.test')
  f.message('stock',f.payload('stock'),f.win.location.origin,{})
  f.message('stock',{...f.payload('stock'),width:NaN})
  f.message('stock',{...f.payload('stock'),rect:{left:0,top:0,width:900,height:60}})
  assert.equal(f.changes(),initial)
  f.message('stock');assert.equal(f.panes.stock.dataset.previewReady,'true')
  assert.match(f.panes.stock.anchor.style.cssText,/--item-top:50%/)
  f.click(f.buttons[1]);assert.equal(f.panes.stock.dataset.previewReady,'false')
  f.message('stock');assert.equal(f.panes.stock.dataset.previewReady,'false')
  f.message('stock',f.payload('stock',sourceDetails[1]));assert.equal(f.panes.stock.dataset.previewReady,'true')
  assert.equal(f.buttons[1]['aria-pressed'],'true')
  for(const pane of Object.values(f.panes)){assert.equal(pane.sku.textContent,'EL-SR-000001');assert.equal(pane.anchor.dataset.sourceId,'receipt:101:2');assert.equal(pane.sent.at(-1).origin,f.win.location.origin)}
  assert.equal(f.panes.receipt.value.textContent,'2,000 个');assert.equal(f.panes.stock.value.textContent,'+2,000 个');assert.equal(f.panes.finance.value.textContent,'¥400.00')
  assert.match(f.summary.textContent,/贴片电阻.*库存 \+2,000.*应付 ¥400.00/)
  const count=f.changes();f.click({dataset:{sourceDetail:'mcu'}});assert.equal(f.changes(),count)
  for(const callback of f.timerCallbacks.values())callback()
  assert.equal(f.panes.receipt.error.hidden,false)
  f.panes.stock.frame.dispatchEvent(new Event('load'));assert.equal(f.panes.stock.dataset.previewReady,'false')
  destroy();assert.equal(f.timerCallbacks.size,0)
  const finalCount=f.changes();f.click(f.buttons[2]);f.message('stock');assert.equal(f.changes(),finalCount)
  const en=detailFixture(),stop=mountSourceDetails(en.scene,'en',en.changed,en.win);en.click(en.buttons[2]);assert.match(en.summary.textContent,/Ceramic capacitor.*payable ¥400.00/);stop()
})
test('关联矩形拒绝负值和错误来源行',()=>{
  const f=detailFixture(),data=f.payload('receipt')
  assert.equal(validPreviewRow(data,'receipt',sourceDetails[0]),true)
  for(const rect of [{...data.rect,left:-1},{...data.rect,height:0},{...data.rect,top:Infinity}])assert.equal(Boolean(validPreviewRow({...data,rect},'receipt',sourceDetails[0])),false)
  assert.equal(validPreviewRow({...data,sourceId:'receipt:101:2'},'receipt',sourceDetails[0]),false)
})

// 真实页面可先读，连线只能在真实行已校验后出现；快速选择不应退回整屏加载。
test('原界面就绪独立于行定位，加载失败立即结束等待，重载不保留旧矩形',()=>{
  const f=detailFixture(),destroy=mountSourceDetails(f.scene,'zh-CN',f.changed,f.win)
  const ready={type:'nexora:preview-ready',surface:'stock',width:1800,height:1200}
  f.message('stock',ready,'https://foreign.test');assert.notEqual(f.panes.stock.dataset.viewReady,'true')
  f.message('stock',{...ready,width:Infinity});assert.notEqual(f.panes.stock.dataset.viewReady,'true')
  f.message('stock',ready);assert.equal(f.panes.stock.dataset.viewReady,'true')
  assert.equal(f.panes.stock.dataset.previewReady,'false')
  assert.match(f.panes.stock.frame.style.transform,/scale\(0\.4\)/)
  assert.equal(f.panes.stock.sent.at(-1).data.key,'mcu')
  f.click(f.buttons[2]);assert.equal(f.panes.stock.dataset.viewReady,'true')
  assert.equal(f.panes.stock.dataset.previewReady,'false')
  f.message('stock',f.payload('stock',sourceDetails[2]));assert.equal(f.panes.stock.dataset.previewReady,'true')
  f.panes.stock.frame.dispatchEvent(new Event('load'))
  assert.equal(f.panes.stock.dataset.viewReady,'false');assert.equal(f.panes.stock.dataset.previewReady,'false')
  f.message('stock',{type:'nexora:preview-error',surface:'stock'})
  assert.equal(f.panes.stock.error.hidden,false)
  assert.equal(f.timerCallbacks.size,2)
  destroy()
})
