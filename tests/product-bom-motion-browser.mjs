// 对隔离预览的真实共享表格逐帧验收；不连接正式服务、不修改业务资料。
import assert from 'node:assert/strict'
import { pathToFileURL } from 'node:url'
const modulePath=process.env.NEXORA_PLAYWRIGHT_MODULE
if(!modulePath) throw Error('请设置 NEXORA_PLAYWRIGHT_MODULE 为已安装的 Playwright 入口。')
const {chromium}=await import(pathToFileURL(modulePath).href)
const origin=process.env.NEXORA_PRODUCT_PREVIEW_URL || 'http://127.0.0.1:8787'
const browser=await chromium.launch({headless:true,channel:process.env.NEXORA_CHROMIUM_CHANNEL || 'chrome'})
try {
 const page=await browser.newPage({viewport:{width:1600,height:1000}})
 const errors=[];page.on('pageerror',error=>errors.push(error.message))
 // 在预览响应中增加共享下层配方，覆盖两层展开与同一物料的独立分支。
 await page.route('**/scripts/site-preview/product-fixtures.mjs*',async route=>{
  const response=await route.fetch()
  const body=(await response.text()).replace('export const productPreviewOperations',`
productPreviewBoms.push({...productPreviewBoms[1],id:5,product_material_id:1,lines:[
 {id:50,component_material_id:2,sku:'QA-LEAF',material_name:'动画验收叶子',unit:'件',quantity:'3'}]})
productPreviewBoms.find(bom=>bom.id===4).lines[1]={...productPreviewBoms.find(bom=>bom.id===4).lines[1],
 component_material_id:1,component_bom_id:5,component_bom_version:2,component_bom_status:'active',sku:'QA-SHARED',material_name:'动画验收共享组件'}
export const productPreviewOperations`)
  await route.fulfill({response,body})
 })
 await page.goto(`${origin}/scripts/site-preview/index.html?qa=products&theme=dark#/workspace/products`)
 await page.locator('[data-structure-key="4/40"] .structure-toggle').waitFor()
 const marker=key=>page.locator(`[data-structure-key="${key}"]`)
 const click=key=>marker(key).locator('.structure-toggle').evaluate(el=>el.click())
 const settle=async()=>{await page.waitForTimeout(30);await page.waitForFunction(()=>!document.querySelector('[data-bom-motion],[data-structure-entering]'),{},{timeout:3000})}
 await settle()
 const sample=key=>page.evaluate(async key=>{
  const table=document.querySelector('.structure-table'),frames=[]
  const read=()=>({height:table.getBoundingClientRect().height,
   rows:[...table.querySelectorAll('[data-structure-key]')].map(el=>{
    const row=el.closest('tr'),cell=row.querySelector('.vxe-cell')
    return {key:el.dataset.structureKey,height:row.getBoundingClientRect().height,
     opacity:Number(getComputedStyle(cell).opacity),inert:row.inert,hidden:row.getAttribute('aria-hidden')}
   })})
  frames.push(read());table.querySelector(`[data-structure-key="${key}"] .structure-toggle`).click()
  const start=performance.now()
  await new Promise(resolve=>{function tick(){frames.push(read());if(performance.now()-start<360)requestAnimationFrame(tick);else resolve()}requestAnimationFrame(tick)})
  return frames
 },key)
 const checkMotion=(frames,opening)=>{
  const from=frames[0].height,to=frames.at(-1).height
  assert.ok(opening?to>from+20:from>to+20)
  assert.ok(frames.some(frame=>frame.height>Math.min(from,to)+2 && frame.height<Math.max(from,to)-2),'表格外框也必须有中间高度')
  const children=frames.flatMap(frame=>frame.rows.filter(row=>row.key.startsWith('4/40/')))
  assert.ok(children.some(row=>row.opacity>0 && row.opacity<1),'子行需要淡入淡出')
  // 各帧沿同一方向推进，不能先闪到自然高度再回到动画起点。
  for(let index=1;index<frames.length;index++){
   const delta=frames[index].height-frames[index-1].height
   assert.ok(opening?delta>=-2:delta<=2)
  }
 }
 const opening=await sample('4/40');checkMotion(opening,true)
 assert.equal(opening.at(-1).rows.length,5)
 await marker('4/40/20').locator('.structure-sku').focus()
 const closing=await sample('4/40');checkMotion(closing,false)
 assert.ok(closing.some(frame=>frame.rows.some(row=>row.key.startsWith('4/40/') && row.inert && row.hidden==='true')))
 assert.equal(await marker('4/40').locator('.structure-toggle').evaluate(el=>el===document.activeElement),true)
 assert.equal(closing.at(-1).rows.length,2)
 // 深层与兄弟分支同时存在，收起一个分支不影响另一个分支。
 await click('4/40');await settle()
 await click('4/40/20');await settle()
 await click('4/41');await settle()
 assert.equal(await marker('4/40/20/50').count(),1)
 assert.equal(await marker('4/41/50').count(),1)
 await click('4/40');await settle()
 assert.equal(await marker('4/40/20/50').count(),0)
 assert.equal(await marker('4/41/50').count(),1)
 // 连续反向从当前几何继续，最终状态和数量必须正确且没有 inert 残留。
 for(let i=0;i<5;i++){await click('4/40');await page.waitForTimeout(35)}
 await settle()
 assert.equal(await marker('4/40/20/50').count(),1)
 assert.equal(await page.locator('.structure-table tr[inert]').count(),0)
 assert.equal(await marker('4/40/20/50').evaluate(el=>el.closest('tr').querySelector('.structure-quantity').textContent),'3.000')
 // 切换当前产品会替换整份 BOM，离场的旧行不能复活。
 await click('4/40')
 await page.locator('.tree-series').nth(1).evaluate(el=>el.click())
 await page.waitForTimeout(260)
 await page.locator('.tree-children .tree-model').first().click()
 await settle()
 assert.equal(await page.locator('[data-structure-key^="4/"]').count(),0)
 // 动画未完成时切换历史版本，只保留新版本真实的行路径。
 await click('2/20')
 await page.locator('.bom-version-choice .workspace-select').click()
 await page.locator('.n-base-select-option').filter({hasText:'V1'}).click()
 await settle()
 assert.equal(await page.locator('[data-structure-key^="2/"]').count(),0)
 assert.ok(await page.locator('[data-structure-key^="1/"]').count()>0)
 // 减少动态效果时直接更新目录，不能启动单元格动画。
 await page.emulateMedia({reducedMotion:'reduce'})
 await page.locator('.tree-series').nth(0).evaluate(el=>el.click())
 await page.locator('.tree-children .tree-model').first().click()
 await settle()
 const reduced=await sample('4/40')
 assert.ok(reduced.every(frame=>Math.abs(frame.height-reduced[0].height)<2 || Math.abs(frame.height-reduced.at(-1).height)<2))
 assert.equal(await page.locator('.structure-table').evaluate(el=>el.getAnimations({subtree:true}).length),0)
 await page.setViewportSize({width:1000,height:850});await settle()
 assert.equal(await marker('4/40/20').count(),1)
 await page.screenshot({path:'/private/tmp/nexora-bom-motion.png',fullPage:true})
 assert.deepEqual(errors,[])
 console.log('PASS: 表格与子行展开收起中间帧、多层独立分支、离场锁定与焦点、快速反向、切换产品与版本、减少动态效果和窄窗口。')
} finally {await browser.close()}
