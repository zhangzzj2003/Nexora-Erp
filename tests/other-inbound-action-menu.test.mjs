import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp, h, reactive } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

// 替换弹层外壳以触发真实选择回调，验证菜单搬迁没有绕过业务权限与禁用约束。
test('操作菜单保留详情完整布局，拦截未知键和过期选择',async t=>{
 const server=await createServer({configFile:false,plugins:[{
  name:'inbound-action-menu-fixture',enforce:'pre',
  transform(code,id){if(id.endsWith('/OtherInboundActions.vue'))return code.replace("'naive-ui'","'virtual:action-menu'")},
  resolveId(id,importer){
   if(id==='virtual:action-menu')return '\0action-menu'
   if(!importer?.endsWith('OtherInboundActions.vue'))return
   if(id==='naive-ui')return '\0action-menu'
   if(id.endsWith('AppButton.vue'))return '\0action-button'
  },
  load(id){
   if(id==='\0action-menu')return `import {h,defineComponent} from 'vue';export const captured={};export const NButton=defineComponent({props:['disabled'],setup(p,{slots,attrs}){return()=>h('button',{...attrs,disabled:p.disabled},slots.default?.())}});
    export const NDropdown=defineComponent({props:['options','show','disabled'],setup(p,{slots,attrs}){
     Object.assign(captured,{props:p,attrs});return()=>h('span',slots.default?.())}})`
   if(id==='\0action-button')return `import {h} from 'vue';export default {props:['disabled'],setup(p,{slots,attrs}){
    return()=>h('button',{...attrs,disabled:p.disabled},slots.default?.())}}`
  }
 },vue()],server:{middlewareMode:true,hmr:false},optimizeDeps:{noDiscovery:true,include:[]}})
 t.after(()=>server.close())
 const {default:Actions}=await server.ssrLoadModule('/src/renderer/src/views/workspace/warehouse/OtherInboundActions.vue')
 const {captured}=await server.ssrLoadModule('\0action-menu')
 const props=reactive({inbound:{status:'draft'},permissions:{create:true,post:true,cancel:true,reverse:true},disabled:false,compact:true})
 const emitted=[]
 let vnode
 const render=()=>renderToString(createSSRApp({render:()=>{vnode=h(Actions,{...props,onAction:key=>emitted.push(key)});return vnode}}))
 const html=await render()
 assert.match(html,/审批 \/ 送审/)
 assert.match(html,/aria-haspopup="menu"/)
 assert.doesNotMatch(html,/>取消</)
 assert.deepEqual(captured.props.options.map(item=>item.key),['cancel'])
 const select=captured.attrs.onSelect
 select('cancel');assert.deepEqual(emitted,['cancel'])
 select('unknown');select('post');assert.deepEqual(emitted,['cancel'])
 props.permissions.cancel=false
 select('cancel');assert.deepEqual(emitted,['cancel'])
 props.permissions.cancel=true
 props.disabled=true
 await render();captured.attrs.onSelect('cancel')
 assert.deepEqual(emitted,['cancel'])
 props.disabled=false;props.inbound.status='posted'
 select('cancel');assert.deepEqual(emitted,['cancel'])
 props.compact=false;props.inbound.status='draft'
 assert.match(await render(),/>取消</)
 await t.test('宽度变化实时展开已授权操作，直接按钮和溢出菜单仍复核禁用与权限',async()=>{
  props.compact=true
  await render()
  const setup=vnode.component.setupState
  // 使用真实组件计算链模拟浏览器测得的按钮宽度，验证布局与事件而非另一套业务规则。
  setup.buttonWidths=[104,52]
  setup.availableWidth=164
  assert.deepEqual(setup.visibleItems.map(item=>item.key),['approval','cancel'])
  assert.deepEqual(setup.menuOptions,[])
  setup.run('cancel');assert.deepEqual(emitted,['cancel','cancel'])
  setup.availableWidth=163
  assert.deepEqual(setup.visibleItems,[])
  assert.deepEqual(setup.menuOptions.map(item=>item.key),['approval','cancel'])
  setup.selectMore('approval');assert.deepEqual(emitted,['cancel','cancel','approval'])
  vnode.component.props.disabled=true
  setup.run('cancel');setup.selectMore('cancel')
  assert.deepEqual(emitted,['cancel','cancel','approval'])
  vnode.component.props.disabled=false
  props.permissions.cancel=false
  setup.run('cancel');setup.selectMore('cancel')
  assert.deepEqual(emitted,['cancel','cancel','approval'])
  setup.buttonWidths=[104]
  assert.equal(setup.visibleItems.length,1)
  assert.deepEqual(setup.menuOptions,[])
 })
})
