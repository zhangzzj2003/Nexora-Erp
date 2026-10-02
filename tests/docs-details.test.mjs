import { test } from 'node:test'
import assert from 'node:assert/strict'
import { sourceDetails, originalCamera, measureDisplayItem, detailMagnification, detailSource, detailCanvas, detailWindowLayout, mountSourceDetails } from '../docs/site/source-details.mjs'
import { receipts, ledger, receivablesPayables } from '../scripts/site-preview/fixtures.mjs'
import { sceneAt, windowGeometry, projectWindowPoint, connectionEndpoints } from '../docs/site/scene-geometry.mjs'

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

// 本地字段用未变换的 offset 定位，外部窗口与镜头缩放都不能改变关联来源。
test('原位字段定位合并连续单元格，拒绝缺失、越界及错误父节点',()=>{
  const canvas={offsetWidth:1800,offsetHeight:1200}
  const parent={offsetLeft:300,offsetTop:200,offsetParent:canvas}
  const nodes=[{offsetLeft:20,offsetTop:40,offsetWidth:220,offsetHeight:60,offsetParent:parent},{offsetLeft:240,offsetTop:40,offsetWidth:300,offsetHeight:60,offsetParent:parent}]
  canvas.querySelectorAll=()=>nodes
  assert.deepEqual(measureDisplayItem(canvas,sourceDetails[0]),{width:1800,height:1200,rect:{left:320,top:240,width:520,height:60}})
  nodes[1].offsetLeft=1600
  assert.equal(measureDisplayItem(canvas,sourceDetails[0]),null)
  nodes[1].offsetLeft=240;nodes[1].offsetParent=null
  assert.equal(measureDisplayItem(canvas,sourceDetails[0]),null)
  canvas.querySelectorAll=()=>[]
  assert.equal(measureDisplayItem(canvas,sourceDetails[0]),null)
  assert.equal(measureDisplayItem(canvas,{key:'invalid'}),null)
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
  const scene=new EventTarget(),win=new EventTarget(),fields=()=>({textContent:''})
  const buttons=sourceDetails.map(detail=>({dataset:{sourceDetail:detail.key},setAttribute(name,value){this[name]=value}}))
  const panes=Object.fromEntries(['receipt','stock','finance'].map(key=>{
    const anchor={style:{},dataset:{}},name=fields(),sku=fields(),value=fields()
    const canvas={style:{},offsetWidth:1800,offsetHeight:1200,missing:false}
    canvas.querySelectorAll=selector=>canvas.missing ? [] : [{offsetLeft:400,offsetTop:300+sourceDetails.findIndex(d=>selector.includes(d.key))*70,offsetWidth:580,offsetHeight:56,offsetParent:canvas}]
    const pane={clientWidth:720,clientHeight:480,dataset:{detailKey:key},querySelector:selector=>({'[data-display-canvas]':canvas,'[data-real-anchor]':anchor,'[data-detail-name]':name,'[data-detail-sku]':sku,'[data-detail-value]':value})[selector]}
    return [key,{...pane,canvas,anchor,name,sku,value}]
  }))
  const summary=fields();let changes=0
  scene.querySelectorAll=()=>buttons
  scene.querySelector=selector=>selector==='[data-detail-summary]'?summary:panes[selector.match(/"([a-z]+)"/)?.[1]]
  const emit=(type,target)=>{const event=new Event(type);Object.defineProperty(event,'target',{value:{closest:()=>target}});scene.dispatchEvent(event)}
  return {scene,win,panes,buttons,summary,emit,changed:()=>{changes++},changes:()=>changes}
}
// 原位展示同步完成选择和布局，没有 iframe 消息、计时器或加载中间态。
test('首帧同步显示，切换物料立即更新三窗来源、金额和锚点，卸载清理事件',()=>{
  const f=detailFixture(),destroy=mountSourceDetails(f.scene,'zh-CN',f.changed,f.win)
  for(const pane of Object.values(f.panes)){
    assert.equal(pane.dataset.previewReady,'true')
    assert.match(pane.canvas.style.transform,/scale\(0\.4\)/)
  }
  f.emit('click',f.buttons[1])
  assert.equal(f.buttons[1]['aria-pressed'],'true')
  for(const pane of Object.values(f.panes)){assert.equal(pane.sku.textContent,'EL-SR-000001');assert.equal(pane.anchor.dataset.sourceId,'receipt:101:2');assert.equal(pane.dataset.previewReady,'true')}
  assert.equal(f.panes.receipt.value.textContent,'2,000 个');assert.equal(f.panes.stock.value.textContent,'+2,000 个');assert.equal(f.panes.finance.value.textContent,'¥400.00')
  assert.match(f.summary.textContent,/贴片电阻.*库存 \+2,000.*应付 ¥400.00/)
  const count=f.changes();f.emit('click',{dataset:{sourceDetail:'unknown'}});assert.equal(f.changes(),count)
  destroy();f.emit('click',f.buttons[2]);f.win.dispatchEvent(new Event('resize'));assert.equal(f.changes(),count)
  const en=detailFixture(),stop=mountSourceDetails(en.scene,'en',en.changed,en.win);en.emit('click',en.buttons[2]);assert.match(en.summary.textContent,/Ceramic capacitor.*payable ¥400.00/);stop()
})
test('缺失字段只隐藏关联锚点，保留原位界面；字段恢复后重新对齐',()=>{
  const f=detailFixture(),stop=mountSourceDetails(f.scene,'zh-CN',f.changed,f.win)
  stop.camera(1)
  assert.match(f.panes.stock.canvas.style.transform,/scale\(1\.158/)
  f.panes.stock.canvas.missing=true;stop.camera()
  assert.equal(f.panes.stock.dataset.previewReady,'false')
  assert.match(f.panes.stock.canvas.style.transform,/scale\(0\.4\)/)
  assert.equal(f.panes.receipt.dataset.previewReady,'true')
  f.panes.stock.canvas.missing=false;f.win.dispatchEvent(new Event('resize'))
  assert.equal(f.panes.stock.dataset.previewReady,'true')
  stop()
})
test('手机取景范围限定在零到一，不改变示例内容或镜头字号',()=>{
  const f=detailFixture(),stop=mountSourceDetails(f.scene,'zh-CN',f.changed,f.win)
  f.panes.stock.clientWidth=360;stop.camera(1)
  const control={dataset:{previewPan:'stock'},value:'100'}
  f.emit('input',control)
  assert.equal(f.panes.stock.dataset.previewPan,'1')
  assert.match(f.panes.stock.canvas.style.transform,/scale\(1\.5\)/)
  control.value='200';f.emit('input',control);assert.equal(f.panes.stock.dataset.previewPan,'1')
  control.value='NaN';f.emit('input',control);assert.equal(f.panes.stock.dataset.previewPan,'1')
  assert.equal(f.panes.stock.sku.textContent,'EL-IC-000001')
  stop()
})
