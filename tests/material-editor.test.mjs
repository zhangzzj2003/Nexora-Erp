import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp, h } from 'vue'
import { createPinia } from 'pinia'
import { setup as setupSsrStyles } from '@css-render/vue3-ssr'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { materialDraft } from '../src/renderer/src/views/workspace/catalog/material-form.ts'

test('物料编辑器显示真实只读编码、必填项及分类参数，忙碌/断线时阻止保存', async t => {
  const server=await createServer({configFile:false,plugins:[vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {default:Editor}=await server.ssrLoadModule('/src/renderer/src/views/workspace/catalog/MaterialEditor.vue')
  const categories=[{code:'EL',name:'电子类',children:[{code:'EL-SR',name:'贴片电阻'}]},{code:'PL',name:'塑料类',children:[{code:'PL-HS',name:'塑料外壳'}]}]
  async function render(form,extra={}) {
    const app=createSSRApp({render:()=>h(Editor,{form,categories,editing:false,busy:false,disconnected:false,...extra})}).use(createPinia())
    setupSsrStyles(app)
    return renderToString(app)
  }
  const empty=await render(materialDraft())
  assert.match(empty,/选择子类后，保存时自动生成/)
  assert.match(empty,/readonly/)
  assert.match(empty,/物料名称[\s\S]*?<input[^>]*required/)
  assert.match(empty,/disabled[^>]*type="submit"|type="submit"[^>]*disabled/)
  const ready=await render({...materialDraft(),category_code:'EL-SR'})
  assert.match(ready,/EL-SR-######/)
  assert.match(ready,/电子参数（选填）/)
  assert.match(ready,/制造商料号/)
  const plastic=await render({...materialDraft(),group_code:'PL',category_code:'PL-HS'})
  assert.match(plastic,/PL-HS-######/)
  assert.doesNotMatch(plastic,/电子参数（选填）/)
  const edit=await render({...materialDraft(),sku:'OLD',version:2},{editing:true})
  assert.match(edit,/value="OLD"/)
  assert.match(edit,/修改原因[\s\S]*?<input[^>]*required/)
  assert.match(edit,/未分类（保留旧资料）/)
  for(const extra of [{busy:true},{disconnected:true}]) {
    const blocked=await render({...materialDraft(),category_code:'EL-SR'},extra)
    assert.match(blocked,/<fieldset[^>]*disabled/)
    assert.match(blocked,/disabled[^>]*type="submit"|type="submit"[^>]*disabled/)
  }
})
