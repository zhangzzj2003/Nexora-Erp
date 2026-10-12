import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { test } from 'node:test'
import { createRenderer, h, nextTick, reactive, toRaw } from 'vue'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createServer, normalizePath } from 'vite'
import vue from '@vitejs/plugin-vue'

// 运行真实组件事件与价格联动，输入外壳只模拟浏览器焦点和校验边界。
test('金额点击编辑、确认、取消、禁用与必填显露保留真实价格依据', async t => {
  const files=['app/AppInlineNumber.vue','workspace/WorkspacePurchasePriceInput.vue']
  const modules=new Map(files.map(file=>{
    const filename=resolve('src/renderer/src/components',file), id=normalizePath(filename)+'.client.ts'
    return [id,compileScript(parse(readFileSync(filename,'utf8'),{filename}).descriptor,{id:file,inlineTemplate:true}).content]
  }))
  const server=await createServer({configFile:false,plugins:[{name:'inline-number-test',enforce:'pre',
    resolveId(id){
      if(modules.has(id))return id
      if(id.endsWith('/AppInlineNumber.vue'))return [...modules.keys()][0]
      if(id.endsWith('/AppButton.vue'))return '\0inline-button'
      if(id.endsWith('/AppInput.vue'))return '\0inline-input'
    },load(id){
      if(modules.has(id))return modules.get(id)
      if(id==='\0inline-button')return `import {defineComponent,h} from 'vue';export default defineComponent({setup(p,{attrs,slots}){return()=>h('button',attrs,slots.default?.())}})`
      if(id==='\0inline-input')return `import {defineComponent,h} from 'vue';export default defineComponent({props:['modelValue'],emits:['update:modelValue'],setup(p,{attrs,emit}){return()=>h('input',{...attrs,value:p.modelValue,onInput:e=>emit('update:modelValue',e.target.value)})}})`
    }
  },vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'})
  t.after(()=>server.close())
  const {default:Price}=await server.ssrLoadModule([...modules.keys()][1])
  let focused=null, valid=true, reports=0
  const flatten=node=>[node,...node.children.flatMap(flatten)]
  const element=type=>({type,props:{},children:[],parent:null,text:'',style:{},
    querySelector(selector){return flatten(this).find(n=>n.type===selector)??null},
    focus(){focused=this},select(){},reportValidity(){reports++;return valid}})
  const renderer=createRenderer({createElement:element,createText:text=>({...element('#text'),text}),createComment:text=>({...element('#comment'),text}),
    setText:(node,text)=>{node.text=text},setElementText:(node,text)=>{node.children=[];node.text=text},patchProp:(node,key,_,value)=>{node.props[key]=value},
    parentNode:node=>node.parent,nextSibling:node=>node.parent?.children[node.parent.children.indexOf(node)+1]??null,
    insert(node,parent,anchor=null){if(node.parent)node.parent.children.splice(node.parent.children.indexOf(node),1);node.parent=parent;const i=anchor?parent.children.indexOf(anchor):-1;parent.children.splice(i<0?parent.children.length:i,0,node)},
    remove(node){if(node.parent)node.parent.children.splice(node.parent.children.indexOf(node),1)}})
  const state=reactive({line:{quantity:'3',pricing_mode:'unit_price',unit_price:'2',line_total:'6.00'},disabled:false})
  const root=element('root'), app=renderer.createApp({render:()=>h(Price,{line:state.line,field:'line_total',disabled:state.disabled,required:true})})
  app.mount(root);t.after(()=>app.unmount())
  const get=type=>flatten(root).find(n=>n.type===type), flush=async()=>{await nextTick();await nextTick()}
  const wrap=()=>flatten(root).find(n=>n.props.onKeydown)
  const key=async value=>{let prevented=false;wrap().props.onKeydown({key:value,preventDefault(){prevented=true},stopPropagation(){}});await flush();return prevented}
  assert.ok(get('button'));assert.equal(get('input').style.display,'none');assert.equal(get('input').props.required,true)
  assert.equal(await key('Enter'),false) // 文本态交给原生按钮激活。
  await get('button').props.onClick();await flush();assert.equal(toRaw(focused),get('input'));assert.equal(get('button'),undefined)
  get('input').props.onInput({target:{value:'10'}});await flush()
  assert.equal(state.line.unit_price,'3.333333333333');assert.equal(state.line.pricing_mode,'total')
  await key('Escape');assert.equal(state.line.line_total,'6.00');assert.equal(state.line.unit_price,'2');assert.equal(state.line.pricing_mode,'unit_price');assert.equal(toRaw(focused),get('button'))
  await get('button').props.onClick();get('input').props.onInput({target:{value:'9'}});await flush()
  valid=false;await key('Enter');assert.equal(get('button'),undefined)
  valid=true;assert.equal(await key('Enter'),true);assert.ok(get('button'));assert.equal(state.line.unit_price,'3')
  await get('button').props.onClick();get('input').props.onBlur();await flush();assert.ok(get('button'))
  let prevented=false;wrap().props.onInvalidCapture({preventDefault(){prevented=true}});await flush();assert.equal(prevented,true);assert.equal(toRaw(focused),get('input'));assert.ok(reports>0)
  state.disabled=true;await flush();assert.ok(get('button').props.disabled);await get('button').props.onClick();await flush();assert.ok(get('button'))
})
