import { readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { sourceImages } from '../docs/site/product-showcase.mjs'
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { sourceCrops, sourceDetails, detailTarget, detailCrop, detailSource, detailCanvas, detailWindowLayout, mountSourceDetails } from '../docs/site/source-details.mjs'
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

test('截图行内矩形完全落在原图和取景视窗内，同一行的投影在三窗间可以直接连线', () => {
  // 图片内容变化必须同时复核坐标，防止新截图继续连到旧的像素位置。
  for(const item of sourceImages) {
    const bytes=readFileSync(new URL(`../docs/site/screenshots/${item.file}`,import.meta.url))
    assert.equal(createHash('sha256').update(bytes).digest('hex').slice(0,12),sourceCrops[item.key].version)
    const highRes=readFileSync(new URL(`../docs/site/screenshots/${item.highRes}`,import.meta.url))
    assert.equal(highRes.readUInt32BE(16),5400); assert.equal(highRes.readUInt32BE(20),3600)
    assert.equal(createHash('sha256').update(highRes).digest('hex').slice(0,12),sourceCrops[item.key].highResVersion)
  }
  for(const crop of Object.values(sourceCrops)) {
    assert.ok(crop.x>=0 && crop.x+crop.width<=1800 && crop.y>=0 && crop.y+crop.height<=1200)
    for(const detail of sourceDetails) {
      const key=Object.keys(sourceCrops).find(key=>sourceCrops[key]===crop), rect=detailTarget(key,detail)
      assert.ok(rect.left>=0 && rect.top>=0 && rect.left+rect.width<=100 && rect.top+rect.height<=100)
    }
  }
  for(const key of Object.keys(sourceCrops)) for(const detail of sourceDetails) {
    const crop=detailCrop(key,detail,true), rect=detailTarget(key,detail,true)
    assert.ok(crop.width<=440 && crop.height===112)
    assert.ok(rect.left>0 && rect.left+rect.width<100 && rect.top>=0 && rect.top+rect.height<=100)
  }
  assert.equal(detailTarget('unknown',sourceDetails[0]),null);assert.equal(detailTarget('receipt',{}),null)
  for(const width of [1200,1440,1680]) for(const p of [.45,.8,.92]) for(const detail of sourceDetails) {
    const poses=detailWindowLayout(sceneAt(p).windows).map(item=>windowGeometry(item,width,520))
    const anchors=['receipt','stock','finance'].map((key,index)=>{
      const rect=detailTarget(key,detail), pose=poses[index]
      const y=(168+(rect.top+rect.height/2)/100*568.8/2.5)*pose.scale
      return { opacity:pose.opacity,left:projectWindowPoint(pose,(129.6+rect.left/100*568.8)*pose.scale,y),right:projectWindowPoint(pose,(129.6+(rect.left+rect.width)/100*568.8)*pose.scale,y) }
    })
    assert.ok(connectionEndpoints(anchors[0],anchors[1],width,520),`入库到库存 ${width}/${p}/${detail.key}`)
    if(p>.7) assert.ok(connectionEndpoints(anchors[1],anchors[2],width,520),`库存到应付 ${width}/${p}/${detail.key}`)
  }
})

function detailFixture() {
  const scene=new EventTarget(), fields = () => ({textContent:''})
  const buttons=sourceDetails.map(detail=>({dataset:{sourceDetail:detail.key},setAttribute(name,value){this[name]=value}}))
  const panes=Object.fromEntries(['receipt','stock','finance'].map(key=>{
    const anchor={style:{},dataset:{}},name=fields(),sku=fields(),value=fields()
    const image={style:{}}
    const pane={querySelector:selector=>({'.real-detail-image':image,'[data-real-anchor]':anchor,'[data-detail-name]':name,'[data-detail-sku]':sku,'[data-detail-value]':value})[selector]}
    return [key,{...pane,anchor,name,sku,value}]
  }))
  const summary=fields();let changes=0
  scene.querySelectorAll=()=>buttons
  scene.querySelector=selector=>selector==='[data-detail-summary]'?summary:panes[selector.match(/"([a-z]+)"/)?.[1]]
  const click=button=>{const event=new Event('click');Object.defineProperty(event,'target',{value:{closest:()=>button}});scene.dispatchEvent(event)}
  return {scene,panes,buttons,summary,click,changed:()=>{changes++},changes:()=>changes}
}

test('选择物料同时更新三窗行内位置、数量及金额，拒绝未知按钮，卸载后不再更新', () => {
  const f=detailFixture(), destroy=mountSourceDetails(f.scene,'zh-CN',f.changed)
  const first=f.panes.stock.anchor.style.cssText
  f.click(f.buttons[1])
  assert.equal(f.buttons[1]['aria-pressed'],'true');assert.equal(f.buttons[0]['aria-pressed'],'false')
  for(const pane of Object.values(f.panes)) {assert.equal(pane.sku.textContent,'EL-SR-000001');assert.equal(pane.anchor.dataset.sourceId,'receipt:101:2')}
  assert.notEqual(f.panes.stock.anchor.style.cssText,first)
  assert.equal(f.panes.receipt.value.textContent,'2,000 个');assert.equal(f.panes.stock.value.textContent,'+2,000 个');assert.equal(f.panes.finance.value.textContent,'¥400.00')
  assert.match(f.summary.textContent,/贴片电阻.*入库 2,000.*库存 \+2,000.*应付 ¥400.00/)
  const count=f.changes();f.click({dataset:{sourceDetail:'mcu'}});assert.equal(f.changes(),count)
  destroy();f.click(f.buttons[2]);assert.equal(f.changes(),count)
  const en=detailFixture();mountSourceDetails(en.scene,'en');en.click(en.buttons[2]);assert.match(en.summary.textContent,/Ceramic capacitor.*1,000 received.*payable ¥400.00/)
})
