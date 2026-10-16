import assert from 'node:assert/strict'
import { test } from 'node:test'
import { effectScope, watch } from 'vue'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createProductionActions } from '../src/renderer/src/store/modules/production-actions.ts'

const draft = () => ({product_material_id:11,source_bom_id:7,base_quantity:'2',note:'派生版本说明',
  lines:[{component_material_id:22,quantity:'3',component_bom_id:null}]})
const receipt = overrides => ({id:42,version:2,product_material_id:11,product_name:'控制板',product_sku:'EL-PC-11',
  product_unit:'块',base_quantity:'2',status:'draft',source_bom_id:7,note:'派生版本说明',
  source_bom:{id:7,version:1,product_material_id:11,product_name:'控制板',product_sku:'EL-PC-11'},
  lines:[{id:91,component_material_id:22,quantity:'3',sku:'EL-IC-22',material_name:'微控制器',unit:'个',component_bom_id:null}],
  ...overrides})
const deferred = () => {let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}}

function environment(t,{callApi=async()=>receipt(),refresh=async()=>{},finalize=async()=>{},perform:customPerform}={}) {
  const previous=globalThis.window, scope=effectScope(), calls=[]
  let state,actions
  scope.run(()=>{
    state=createAppState()
    state.server.value={id:'server-one',fingerprint:'certificate-one'}
    state.user.value={id:1,roles:['planner'],permissions:['production.view','bom.create']}
    state.bomForm.value=draft()
    globalThis.window={nexora:{callApi:async(action,payload)=>{calls.push([action,structuredClone(payload)]);return callApi(action,payload)}}}
    // 模拟真实 perform 的顺序：写入、全量刷新、反馈，最后同步解除 busy。
    const perform=customPerform??(async(action,success)=>{
      if(state.busy.value||state.connectionLost.value)return
      state.busy.value=true;state.error.value='';state.notice.value=''
      try {await action();await refresh(state);state.notice.value=success}
      catch(cause){state.error.value=cause.message}
      finally {try{await finalize(state)}finally{state.busy.value=false}}
    })
    actions=createProductionActions(state,perform,()=>{})
  })
  t.after(()=>{scope.stop();globalThis.window=previous})
  return {state,actions,calls}
}

test('BOM 确认创建即清理原稿，刷新完成后返回真实回执，不猜列表最大编号', async t=>{
  const waiting=deferred(), entered=deferred(), ack=receipt()
  const f=environment(t,{callApi:async()=>ack,refresh:async state=>{
    entered.resolve();await waiting.promise
    state.boms.value=[receipt({id:999,product_material_id:33})]
  }})
  const original=f.state.bomForm.value, pending=f.actions.createBom()
  await entered.promise
  assert.equal(f.state.busy.value,true);assert.notEqual(f.state.bomForm.value,original)
  assert.equal(f.state.bomForm.value.product_material_id,0)
  assert.deepEqual(f.calls,[['createBom',draft()]])
  await f.actions.createBom();assert.equal(f.calls.length,1)
  waiting.resolve()
  assert.equal(await pending,ack)
  assert.equal(f.state.busy.value,false)
  assert.deepEqual(f.state.bomForm.value,{product_material_id:0,source_bom_id:null,base_quantity:'1',note:'',lines:[{component_material_id:0,quantity:'1'}]})
  assert.equal(f.state.boms.value[0].id,999)
  assert.match(f.state.notice.value,/草稿已创建/)
})

test('独立新建省略派生来源，真实回执为空来源时仍可返回', async t=>{
  const ack=receipt({source_bom_id:null,source_bom:null})
  const f=environment(t,{callApi:async()=>ack})
  f.state.bomForm.value.source_bom_id=null
  assert.equal(await f.actions.createBom(),ack)
  assert.equal(Object.hasOwn(f.calls[0][1],'source_bom_id'),false)
})

test('BOM 接口失败保留完整草稿，不返回伪造成功身份', async t=>{
  const f=environment(t,{callApi:async()=>{throw Error('保存冲突')}})
  const original=f.state.bomForm.value, line=original.lines[0]
  assert.equal(await f.actions.createBom(),undefined)
  assert.equal(f.state.bomForm.value,original);assert.equal(f.state.bomForm.value.lines[0],line)
  assert.deepEqual(f.state.bomForm.value,draft());assert.match(f.state.error.value,/保存冲突/)
  assert.equal(f.state.busy.value,false)
})

test('合法创建后刷新或审批重读失败仍返回真实回执，清原稿并明确已保存，不能重发旧内容', async t=>{
  for(const stage of ['refresh','approval'])await t.test(stage,async t=>{
    const ack=receipt()
    const f=environment(t,{callApi:async()=>ack,
      refresh:async()=>{if(stage==='refresh')throw Error('刷新暂时失败')},
      finalize:async()=>{if(stage==='approval')throw Error('审批重读失败')}})
    assert.equal(await f.actions.createBom(),ack)
    assert.equal(f.calls.length,1);assert.equal(f.calls[0][0],'createBom')
    assert.equal(f.state.bomForm.value.product_material_id,0)
    assert.deepEqual(f.state.bomForm.value.lines,[{component_material_id:0,quantity:'1'}])
    assert.match(f.state.error.value,/BOM 草稿 #42 已保存，刷新资料失败：/)
    assert.match(f.state.error.value,stage==='refresh'?/刷新暂时失败/:/审批重读失败/)
    assert.equal(f.state.busy.value,false)
  })
})

test('BOM 错产品、错派生来源、非草稿和不完整回执均拒绝清空原稿', async t=>{
  const cases={
    '另一产出物料':()=>receipt({product_material_id:33}),
    '另一派生来源':()=>receipt({source_bom_id:8,source_bom:{id:8,version:1,product_material_id:11,product_name:'控制板',product_sku:'EL-PC-11'}}),
    '丢失派生来源':()=>receipt({source_bom_id:null,source_bom:null}),
    '已经启用的版本':()=>receipt({status:'active'}),
    '只有编号的伪回执':()=>({id:42}),
    '不完整组件':()=>receipt({lines:[{id:91,component_material_id:22,quantity:'3'}]})
  }
  for(const [label,response] of Object.entries(cases))await t.test(label,async t=>{
    const f=environment(t,{callApi:async()=>response()}), original=f.state.bomForm.value
    assert.equal(await f.actions.createBom(),undefined)
    assert.equal(f.state.bomForm.value,original);assert.notEqual(f.state.error.value,'')
    assert.equal(f.calls.length,1)
  })
})

test('BOM 创建受创建权限、忙碌、断线及桌面桥保护', async t=>{
  const cases={
    '没有创建权限':state=>{state.user.value.permissions=['production.view']},
    '正在保存':state=>{state.busy.value=true},
    '连接中断':state=>{state.connectionLost.value=true},
    '没有桌面桥':()=>{globalThis.window.nexora=undefined}
  }
  for(const [label,change] of Object.entries(cases))await t.test(label,async t=>{
    const f=environment(t), original=f.state.bomForm.value
    change(f.state)
    assert.equal(await f.actions.createBom(),undefined)
    assert.equal(f.calls.length,0);assert.equal(f.state.bomForm.value,original)
  })
})

test('BOM 请求与刷新期间会话变化时，迟到回执不能清新账号草稿或驱动定位', async t=>{
  const changes={
    '账号变化':state=>{state.user.value={...state.user.value,id:2}},
    '服务实例变化':state=>{state.server.value={...state.server.value,id:'server-two'}},
    '证书变化':state=>{state.server.value={...state.server.value,fingerprint:'certificate-two'}},
    '创建权限先撤后授':state=>{state.user.value.permissions=[];state.user.value.permissions=['production.view','bom.create']},
    '连接先断后恢复':state=>{state.connectionLost.value=true;state.connectionLost.value=false}
  }
  for(const stage of ['write','refresh'])for(const [label,change] of Object.entries(changes))await t.test(`${stage}-${label}`,async t=>{
    const waiting=deferred(), entered=deferred()
    const f=environment(t,{callApi:async()=>{if(stage==='write'){entered.resolve();await waiting.promise}return receipt()},
      refresh:async()=>{if(stage==='refresh'){entered.resolve();await waiting.promise}}})
    const pending=f.actions.createBom()
    await entered.promise
    change(f.state)
    f.state.bomForm.value={...draft(),product_material_id:55,note:'新会话保留草稿'}
    const fresh=f.state.bomForm.value
    waiting.resolve()
    assert.equal(await pending,undefined)
    assert.equal(f.state.bomForm.value,fresh);assert.equal(f.state.bomForm.value.note,'新会话保留草稿')
  })
})

test('BOM 在请求或刷新期间被替换或修改的草稿不会被旧请求清空', async t=>{
  for(const stage of ['write','refresh'])for(const kind of ['replace','edit'])await t.test(`${stage}-${kind}`,async t=>{
    const waiting=deferred(),entered=deferred()
    const f=environment(t,{callApi:async()=>{if(stage==='write'){entered.resolve();await waiting.promise}return receipt()},
      refresh:async()=>{if(stage==='refresh'){entered.resolve();await waiting.promise}}})
    const pending=f.actions.createBom()
    await entered.promise
    // 内容完全相同但引用不同也属于新草稿；原地改量则须保留最新输入。
    if(kind==='replace')f.state.bomForm.value=draft()
    else f.state.bomForm.value.lines[0].quantity='9'
    const current=f.state.bomForm.value
    waiting.resolve()
    assert.equal(await pending,undefined);assert.equal(f.state.bomForm.value,current)
    assert.equal(f.state.bomForm.value.lines[0].quantity,kind==='edit'?'9':'3')
  })
})

test('BOM 保存解锁触发同步切账号时，旧回执不能清新草稿或返回旧编号', async t=>{
  const f=environment(t)
  const stop=watch(f.state.busy,active=>{
    if(active)return
    f.state.user.value={...f.state.user.value,id:2}
    f.state.bomForm.value={...draft(),product_material_id:55,note:'解锁时的新账号草稿'}
  },{flush:'sync'})
  t.after(stop)
  assert.equal(await f.actions.createBom(),undefined)
  assert.equal(f.state.bomForm.value.note,'解锁时的新账号草稿')
})

test('确认建档清空表单时同步原地填写新输入，不接管被改写的空草稿或返回旧编号', async t=>{
  const f=environment(t)
  const stop=watch(f.state.bomForm,current=>{
    if(current.product_material_id===0)current.note='同步观察者写入的下一份草稿'
  },{flush:'sync'})
  t.after(stop)
  assert.equal(await f.actions.createBom(),undefined)
  assert.equal(f.calls.length,1)
  assert.equal(f.state.bomForm.value.product_material_id,0)
  assert.equal(f.state.bomForm.value.note,'同步观察者写入的下一份草稿')
})

test('BOM 旧排队回调在换账号或换草稿后拒绝发送原写入', async t=>{
  for(const kind of ['account','draft'])await t.test(kind,async t=>{
    let queued
    const f=environment(t,{perform:async action=>{queued=action}})
    assert.equal(await f.actions.createBom(),undefined)
    if(kind==='account')f.state.user.value={...f.state.user.value,id:2}
    else f.state.bomForm.value={...draft(),product_material_id:55}
    await assert.rejects(queued(),/会话或草稿已变化/)
    assert.equal(f.calls.length,0)
  })
})
