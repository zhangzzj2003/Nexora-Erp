// 真实长表格的展开/收回性能取样；通过 CDP 记录绘制与布局，避免只测空卡片。
import assert from 'node:assert/strict'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { writeFile, mkdir } from 'node:fs/promises'
import { join, relative } from 'node:path'
import { execFileSync } from 'node:child_process'
import { pathToFileURL } from 'node:url'
const modulePath = process.env.NEXORA_PLAYWRIGHT_MODULE
if (!modulePath) throw Error('请设置 NEXORA_PLAYWRIGHT_MODULE')
const { chromium } = await import(pathToFileURL(modulePath).href)
const fixture = `
import {createApp,h,ref,nextTick} from 'vue';import {NMessageProvider} from 'naive-ui';
import AppModal from '/src/renderer/src/components/app/AppModal.vue';
import {captureDialogOrigin} from '/src/renderer/src/utils/dialog-origin.ts';
import '/src/renderer/src/style.css';
const originalAnimate=Element.prototype.animate;window.motionSamples=[];window.motionActive=false;Element.prototype.animate=function(...args){const a=originalAnimate.apply(this,args);if(this.matches('[data-app-modal-id],[data-dialog-exit-frame]')){window.motionSamples=[];window.motionStarted=performance.now();window.motionProperties=a.effect.getKeyframes().map(frame=>Object.keys(frame).filter(key=>!['offset','computedOffset','easing','composite'].includes(key)));window.motionActive=true;a.finished.then(()=>window.motionActive=false,()=>window.motionActive=false)}return a};
const show=ref(false);window.fixtureOpened=false;window.fixtureClosed=true;window.samples=[];
window.fixture={async open(){captureDialogOrigin('perf',document.querySelector('#open'));window.fixtureOpened=false;window.fixtureClosed=false;show.value=true;await nextTick()},async close(){window.fixtureClosed=false;show.value=false;await nextTick()}};
const rows=Array.from({length:250},(_,r)=>h('tr',Array.from({length:10},(_,c)=>h('td',{style:'padding:8px;border-bottom:1px solid #ddd'},'记录 '+r+' / '+c))));
createApp({setup:()=>()=>h(NMessageProvider,null,{default:()=>[
 h('button',{id:'open',style:'position:fixed;left:40px;top:40px',onClick:()=>window.fixture.open()},'详情'),
 h(AppModal,{show:show.value,originKey:'perf',preset:'card',title:'长表格性能验收',style:'width:1000px',onAfterEnter:()=>window.fixtureOpened=true,onAfterLeave:()=>window.fixtureClosed=true,'onUpdate:show':v=>show.value=v},
 {default:()=>h('div',{style:'height:560px;overflow:auto',class:'scroll'},[h('table',{style:'border-collapse:collapse;width:100%'},rows)]),footer:()=>h('button',{id:'close',onClick:()=>window.fixture.close()},'关闭')})
]})}).mount('#app');
function sample(time){window.samples.push(time);if(window.motionActive&&time>=window.motionStarted)window.motionSamples.push(time);requestAnimationFrame(sample)}requestAnimationFrame(sample);
`
const server = await createServer({ configFile: false, plugins: [{name:'dialog-baseline-source',enforce:'pre',load(id){
  // 可选地加载修复前提交，保证前后使用同一个表格、采样规则和浏览器。
  if(!process.env.NEXORA_DIALOG_BASELINE_REF)return
  const file=relative(process.cwd(),id).replaceAll('\\','/')
  if(['src/renderer/src/components/app/AppModal.vue','src/renderer/src/utils/dialog-motion.ts','src/renderer/src/utils/dialog-origin.ts'].includes(file))return execFileSync('git',['show',process.env.NEXORA_DIALOG_BASELINE_REF+':'+file],{encoding:'utf8'})
}},vue(), tailwindcss(), {
  name: 'dialog-performance-fixture', resolveId: id => id === '/fixture.js' ? '\0fixture' : undefined,
  load: id => id === '\0fixture' ? fixture : undefined,
  configureServer(server) { server.middlewares.use((req,res,next)=>{if(req.url!=='/')return next();res.setHeader('content-type','text/html');res.end('<html><body><div id="app"></div><script type="module" src="/fixture.js"></script></body></html>')}) }
}], server:{host:'127.0.0.1',port:0}, appType:'custom' })
await server.listen()
let browser
try {
  browser=await chromium.launch({headless:true,channel:'chrome'})
  const page=await browser.newPage({viewport:{width:1280,height:900}})
  const errors=[];page.on('pageerror',e=>{errors.push(e.message);console.error(e.message)})
  await page.goto(server.resolvedUrls.local[0]);await page.waitForSelector('#open')
  // 首次依赖编译不计入动画；正式样本统一使用相同的 CPU 限速。
  await page.evaluate(()=>window.fixture.open());await page.waitForFunction(()=>window.fixtureOpened)
  await page.evaluate(()=>window.fixture.close());await page.waitForFunction(()=>window.fixtureClosed)
  const client=await page.context().newCDPSession(page)
  await client.send('Emulation.setCPUThrottlingRate',{rate:Number(process.env.NEXORA_DIALOG_CPU_RATE || 4)})
  const results=[]
  for(let run=0;run<3;run++)for(const phase of ['open','close']){
    const events=[];const collect=chunk=>events.push(...chunk.value);client.on('Tracing.dataCollected',collect)
    await client.send('Tracing.start',{categories:'devtools.timeline,blink.user_timing',transferMode:'ReportEvents'})
    const outcome=await page.evaluate(async phase=>{
      if(phase==='close')document.querySelector('[data-app-modal-id] .scroll').scrollTop=347
      window.samples=[];const start=performance.now();await window.fixture[phase]();const dispatched=performance.now()-start
      const copy=document.querySelector('[data-dialog-exit-frame]')
      return {dispatched,scroll:copy?.querySelector('.scroll').scrollTop,cellTabIndices:copy?.querySelectorAll('td[tabindex]').length}
    },phase)
    if(phase==='close'){assert.equal(outcome.scroll,347);if(!process.env.NEXORA_DIALOG_BASELINE_REF)assert.equal(outcome.cellTabIndices,0,'副本不能向普通表格单元格批量写入 tabindex')}
    await page.waitForFunction(phase=>phase==='open'?window.fixtureOpened:window.fixtureClosed,phase)
    if(!process.env.NEXORA_DIALOG_BASELINE_REF){
      const properties=await page.evaluate(()=>window.motionProperties)
      for(const keys of properties)assert.deepEqual(keys.sort(),['opacity','transform'],'飞行轨道只能包含合成属性')
      if(phase==='open')assert.equal(await page.locator('[data-app-modal-id]').evaluate(el=>[el,...el.children].every(node=>!node.style.willChange)),true,'完成后释放临时合成提示')
    }
    const gaps=await page.evaluate(()=>window.samples.slice(1).map((time,index)=>time-window.samples[index]))
    const motionGaps=await page.evaluate(()=>window.motionSamples.slice(1).map((time,index)=>time-window.motionSamples[index]))
    const done=new Promise(resolve=>client.once('Tracing.tracingComplete',resolve));await client.send('Tracing.end');await done;client.off('Tracing.dataCollected',collect)
    if(process.env.NEXORA_DIALOG_EVIDENCE_DIR){await mkdir(process.env.NEXORA_DIALOG_EVIDENCE_DIR,{recursive:true});if(run===0)await writeFile(join(process.env.NEXORA_DIALOG_EVIDENCE_DIR,(process.env.NEXORA_DIALOG_PERF_LABEL||'performance')+'-'+phase+'-trace.json'),JSON.stringify(events))}
    const timings=name=>events.filter(e=>e.name===name&&e.ph==='X')
    results.push({run,phase,dispatchMs:Math.round(outcome.dispatched),maxFrameGap:Math.round(Math.max(0,...gaps)),frames:gaps.length,maxMotionFrameGap:Math.round(Math.max(0,...motionGaps)),
      paints:timings('Paint').length,layouts:timings('Layout').length,paintMs:Math.round(timings('Paint').reduce((sum,e)=>sum+(e.dur||0),0)/1000)})
  }
  assert.deepEqual(errors,[])
  if(process.env.NEXORA_DIALOG_EVIDENCE_DIR){await mkdir(process.env.NEXORA_DIALOG_EVIDENCE_DIR,{recursive:true});await writeFile(join(process.env.NEXORA_DIALOG_EVIDENCE_DIR,process.env.NEXORA_DIALOG_PERF_LABEL||'performance.json'),JSON.stringify(results,null,2))}
  console.log(JSON.stringify(results,null,2))
}finally{await browser?.close();await server.close()}
