import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createSSRApp,h} from 'vue'
import {renderToString} from '@vue/server-renderer'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'

// 使用真实来源组件渲染，并点击实际按钮事件，核对关联跳转和原事件只读。
test('重开溯源展示两端号码、终态和操作人时间，关联跳转不执行重开',async t=>{
 const server=await createServer({configFile:false,plugins:[{
  name:'reopen-trace-buttons',enforce:'pre',
  resolveId(id){if(id.endsWith('/AppButton.vue'))return '\0reopen-trace-button'},
  load(id){if(id==='\0reopen-trace-button')return `import {h,defineComponent} from 'vue';export const buttons=[];export default defineComponent({props:['disabled'],setup(p,{attrs,slots}){return()=>{buttons.push({p,attrs});return h('button',{...attrs,disabled:p.disabled},slots.default?.())}}})`}
 },vue()],server:{middlewareMode:true,hmr:false},appType:'custom'})
 t.after(()=>server.close())
 const {default:Trace}=await server.ssrLoadModule('/src/renderer/src/components/workspace/OtherInboundReopenTrace.vue')
 const {buttons}=await server.ssrLoadModule('\0reopen-trace-button')
 const link={id:1,source_id:3,new_id:4,kind:'reversed',source_document_no:'原单-QTRK',new_document_no:'新单-QTRK',created_by:1,created_by_name:'仓库员',created_at:'2026-10-09 14:00'}
 const snapshot=JSON.stringify(link),opened=[]
 const render=async(links,currentId=3,disabled=false)=>{buttons.length=0;return renderToString(createSSRApp({render:()=>h(Trace,{links,currentId,disabled,localTime:x=>'时间 '+x,onOpen:id=>opened.push(id)})}))}
 let html=await render([link])
 for(const text of ['单据溯源流程','原单-QTRK','新单-QTRK','冲销重开新单','仓库员','时间 2026-10-09 14:00'])assert.ok(html.includes(text))
 assert.equal(buttons[0].p.disabled,true);assert.equal(buttons[1].p.disabled,false)
 buttons[1].attrs.onClick();assert.deepEqual(opened,[4])
 await render([link],4);buttons[0].attrs.onClick();assert.deepEqual(opened,[4,3])
 await render([link],3,true);assert.ok(buttons.every(b=>b.p.disabled))
 html=await render([{...link,kind:'cancelled',source_document_no:null,new_document_no:null}])
 assert.match(html,/已取消 → 重开为新单/);assert.match(html,/其他入库 #3/)
 assert.doesNotMatch(await render([]),/单据溯源流程/)
 assert.equal(JSON.stringify(link),snapshot)
})
