// 对隔离产品预览逐帧验收真实动画，不连接正式业务服务。
import assert from 'node:assert/strict'
import { pathToFileURL } from 'node:url'

const modulePath=process.env.NEXORA_PLAYWRIGHT_MODULE
if(!modulePath) throw Error('请设置 NEXORA_PLAYWRIGHT_MODULE 为已安装的 Playwright 入口。')
const {chromium}=await import(pathToFileURL(modulePath).href)
const origin=process.env.NEXORA_PRODUCT_PREVIEW_URL || 'http://127.0.0.1:8785'
const browser=await chromium.launch({headless:true,channel:process.env.NEXORA_CHROMIUM_CHANNEL || 'chrome'})
try {
 const page=await browser.newPage({viewport:{width:1600,height:1000}})
 const errors=[];page.on('pageerror',error=>errors.push(error.message))
 await page.goto(`${origin}/scripts/site-preview/index.html?qa=products&theme=dark#/workspace/products`)
 await page.waitForFunction(()=>document.querySelectorAll('.tree-series').length===4
   && document.querySelectorAll('.tree-children .tree-model').length>0)
 const roots=page.locator('.tree-roots > li')
 const settle=()=>page.waitForFunction(()=>!document.querySelector('.tree-branch-enter-active,.tree-branch-leave-active'))
 await settle()
 // 同一帧发起切换并记录几何，不能用只有首尾两张截图冒充连续动画。
 const sample=async index=>page.evaluate(async index=>{
  const root=document.querySelectorAll('.tree-roots > li')[index]
  const frames=[]
  const read=()=>{
   const branch=root.querySelector('.tree-branch')
   return {height:branch?.getBoundingClientRect().height ?? 0,
    opacity:branch?Number(getComputedStyle(branch).opacity):0,
    inert:branch?.inert ?? false,hidden:branch?.getAttribute('aria-hidden')}
  }
  frames.push(read())
  root.querySelector('.tree-series').click()
  const start=performance.now()
  await new Promise(resolve=>{
   function tick(){frames.push(read());if(performance.now()-start<340)requestAnimationFrame(tick);else resolve()}
   requestAnimationFrame(tick)
  })
  return frames
 },index)
 const initial=await page.locator('.tree-series[aria-expanded="true"]').evaluate(el=>
  [...el.closest('.tree-roots').children].indexOf(el.closest('li')))
 await roots.nth(initial).locator('.tree-model').first().focus()
 const closing=await sample(initial)
 const full=closing[0].height
 assert.ok(full>20)
 assert.ok(closing.some(frame=>frame.height>1 && frame.height<full-1),'收起必须有真实中间高度')
 assert.ok(closing.some(frame=>frame.height>1 && frame.inert && frame.hidden==='true'),'离场即锁定键盘与读屏访问')
 assert.equal(closing.at(-1).height,0)
 assert.equal(await roots.nth(initial).locator('.tree-series').evaluate(el=>el===document.activeElement),true)
 const opening=await sample(initial)
 assert.ok(opening.some(frame=>frame.height>1 && frame.height<full-1),'展开必须有真实中间高度')
 assert.ok(Math.abs(opening.at(-1).height-full)<1)
 assert.equal(opening.at(-1).inert,false)
 // 间距必须随整个分支收回，结束后仍保持上次确认的 10px 留白。
 const gap=await roots.nth(initial).evaluate(root=>root.querySelector('.tree-children').getBoundingClientRect().top-root.querySelector('.tree-series-row').getBoundingClientRect().bottom)
 assert.ok(Math.abs(gap-10)<1)
 // 快速反向、换组及未归组切换后不能残留多个分支或锁住重新展开的节点。
 for(const index of [initial,initial,1,3,0,0,1]){
  await roots.nth(index).locator('.tree-series').evaluate(el=>el.click())
  await page.waitForTimeout(35)
 }
 await settle()
 assert.equal(await page.locator('.tree-series[aria-expanded="true"]').count(),1)
 assert.equal(await roots.nth(1).locator('.tree-series').getAttribute('aria-expanded'),'true')
 assert.equal(await page.locator('.tree-branch').count(),1)
 assert.equal(await page.locator('.tree-branch').evaluate(el=>el.inert),false)
 // 空系列和未归组也要在关闭时完整收回其提示区域。
 for(const index of [2,3]){
  await roots.nth(index).locator('.tree-series').click();await settle()
  assert.equal(await roots.nth(index).locator('.tree-empty').count(),1)
  const emptyClosing=await sample(index)
  assert.ok(emptyClosing.some(frame=>frame.height>1 && frame.height<emptyClosing[0].height-1))
  assert.equal(emptyClosing.at(-1).height,0)
 }
 await page.emulateMedia({reducedMotion:'reduce'})
 await roots.nth(0).locator('.tree-series').click();await settle()
 assert.equal(await roots.nth(0).locator('.tree-branch').evaluate(el=>getComputedStyle(el).transitionDuration),'0s')
 const reduced=await sample(0)
 assert.ok(reduced.every(frame=>frame.height<1 || Math.abs(frame.height-reduced[0].height)<1),'减少动态效果时不应播放中间高度')
 assert.deepEqual(errors,[])
 console.log('PASS: 展开/收起中间帧、10px 间距、离场焦点与 inert、快速切换、空系列、未归组及减少动态效果。')
} finally {await browser.close()}
