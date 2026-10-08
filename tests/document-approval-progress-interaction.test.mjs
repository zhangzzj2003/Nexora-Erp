import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { test } from 'node:test'
import { createRenderer, h, nextTick, reactive } from 'vue'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

// 实际组件在 Vue 内存渲染器运行，触发真实按钮回调；过渡外壳替换为普通容器，动画另在浏览器验证。
test('点击节点及历次送审联动意见和依据，刷新及换单正确复位且不修改源记录', async t => {
  const filename = resolve('src/renderer/src/components/workspace/DocumentApprovalProgress.vue')
  const id = filename + '.client.ts'
  const source = readFileSync(filename, 'utf8').replace('<Transition name="approval-record" mode="out-in">', '<div>').replace('</Transition>', '</div>')
  const { descriptor } = parse(source, { filename })
  const compiled = compileScript(descriptor, { id: 'approval-interaction', inlineTemplate: true }).content
  const server = await createServer({ configFile: false, plugins: [{name:'approval-client-test', enforce:'pre',
    resolveId(value) { if (value === id) return id; if (value.endsWith('/AppButton.vue') || value === './AppButton.vue') return '\0approval-test-button' },
    load(value) {
      if (value === id) return compiled
      if (value === '\0approval-test-button') return `import {defineComponent,h} from 'vue';export default defineComponent({inheritAttrs:false,setup(_,ctx){return()=>h('button',ctx.attrs,ctx.slots.default?.())}})`
    }
  }, vue()], optimizeDeps: {noDiscovery:true,include:[]}, server:{middlewareMode:true,hmr:false}, appType:'custom' })
  t.after(() => server.close())
  const {default: Progress} = await server.ssrLoadModule(id)
  // 元素仅提供渲染与查询边界，不模拟浏览器的滚动和尺寸。
  const element = type => ({ type, props:{}, children:[], parent:null, text:'', querySelector:()=>null })
  const renderer = createRenderer({
    createElement: element, createText: text => ({...element('#text'),text}), createComment: text => ({...element('#comment'),text}),
    setText: (node,text) => {node.text=text}, setElementText: (node,text) => {node.children=[];node.text=text},
    patchProp: (node,key,_,value) => {node.props[key]=value}, parentNode: node => node.parent,
    nextSibling: node => node.parent?.children[node.parent.children.indexOf(node)+1] ?? null,
    insert(node,parent,anchor=null) { if(node.parent) node.parent.children.splice(node.parent.children.indexOf(node),1);node.parent=parent;
      const index=anchor?parent.children.indexOf(anchor):-1;parent.children.splice(index<0?parent.children.length:index,0,node) },
    remove(node) {if(node.parent){node.parent.children.splice(node.parent.children.indexOf(node),1);node.parent=null}}
  })
  const event = (id,generation,action,step,name=null) => ({id,version:id,generation,action,step,step_name:name,actor_id:id,
    actor_name:`人员${id}`,reason:`意见${id}`,evidence:`现场${id}`,created_at:'2026-10-08T07:00:00Z'})
  const record = reactive({document_type:'MaintenanceJob',document_id:1,intent:'execute',generation:2,version:4,
    business_status:'draft',status:'submitted',current_step:0,steps:[{name:'新批准',role:null}],
    events:[event(1,1,'submit',0),event(2,1,'approve',0,'旧审核'),event(3,1,'withdraw',1),event(4,2,'submit',0)]})
  const before = structuredClone({...record,events:record.events.map(row=>({...row})),steps:record.steps.map(row=>({...row}))})
  const root=element('root'), app=renderer.createApp({render:()=>h(Progress,{record,roles:[],localTime:value=>value})})
  app.mount(root);t.after(()=>app.unmount())
  const flatten = node => [node,...node.children.flatMap(flatten)]
  const text = node => (node.type==='#comment'?'':node.text)+node.children.map(text).join('')
  const click = async predicate => {
    const button=flatten(root).find(node=>node.type==='button' && predicate(node))
    assert.ok(button,JSON.stringify(flatten(root).filter(node=>node.type==='button').map(node=>({text:text(node),label:node.props['aria-label']}))));button.props.onClick();await nextTick();await nextTick()
  }
  const panel = () => flatten(root).find(node=>node.props.class==='approval-node-records')
  assert.match(text(panel()),/等待新批准处理/)
  await click(node=>text(node).includes('查看最近记录'))
  assert.match(text(panel()),/送审 · 人员4/);assert.match(text(panel()),/意见4/);assert.match(text(panel()),/现场依据：现场4/)
  await click(node=>text(node).trim()==='第 1 次送审')
  assert.match(text(panel()),/撤回 · 人员3/)
  assert.doesNotMatch(text(root),/新批准/)
  await click(node=>node.props['aria-label']==='查看旧审核记录，已完成')
  assert.match(text(panel()),/旧审核 · 人员2/);assert.match(text(panel()),/意见2/)
  assert.doesNotMatch(text(panel()),/意见4/)
  await click(node=>text(node).includes('第 2 次送审'))
  assert.match(text(panel()),/等待新批准处理/)
  // 相同版本的快照刷新保留选择；真实审批推进到执行则自动选中新待办。
  await click(node=>node.props['aria-label']==='查看送审记录，已送审')
  record.events=[...record.events];await nextTick();assert.match(text(panel()),/意见4/)
  assert.deepEqual({...record,events:record.events.map(row=>({...row})),steps:record.steps.map(row=>({...row}))},before)
  record.events.push(event(5,2,'approve',0,'新批准'));record.current_step=1;record.status='approved';record.version=5
  await nextTick();await nextTick();assert.match(text(panel()),/等待业务执行/)
  // 换单据不泄漏上一单的轮次和节点。
  record.document_id=2;record.version=0;record.generation=0;record.current_step=0;record.status='draft';record.steps=[];record.events=[]
  await nextTick();await nextTick();assert.match(text(panel()),/等待提交审批/);assert.doesNotMatch(text(root),/人员4|第 1 次送审/)
})
