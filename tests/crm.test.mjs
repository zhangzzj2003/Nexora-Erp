import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createCrmActions,emptyCrmForms } from '../src/renderer/src/store/modules/crm-actions.ts'
import { crmFormError,quoteActions,crmSnapshotRows } from '../src/renderer/src/views/workspace/sales/crm-display.ts'
import { callBackend, fetchCrmQuotePdf } from '../src/main/backend.ts'
import { parseContactCsv, parseContactCsvBytes } from '../src/renderer/src/views/workspace/sales/contact-import.ts'
import { parseOpportunityCsv, parseOpportunityCsvBytes } from '../src/renderer/src/views/workspace/sales/opportunity-import.ts'
import { validateContactImportPreview, validateContactImportResult } from '../src/shared/contact-import-validation.ts'
import { validateOpportunityImportPreview, validateOpportunityImportResult } from '../src/shared/opportunity-import-validation.ts'
import { validateCrmForecast } from '../src/shared/crm-forecast-validation.ts'
import { canVisitRoute,routeByKey } from '../src/renderer/src/router/workspace-routes.ts'

const permissions=['crm.view','crm_contact.manage','crm_activity.manage','crm_opportunity.manage','crm_quote.create','crm_quote.submit','crm_quote.convert','sales_order.create']
const quote={id:1,version:3,status:'approved',opportunity_version:2,opportunity_stage:'qualified',review_blocked:[1],expired:false,contact_active:true}
const quoteInput={opportunity_id:1,contact_id:null,reference:'Q-1',valid_until:'2030-01-31',terms:'确认后交货',lines:[{material_id:1,quantity:'1.005',unit_price:'0.9999'}]}
const overview={contacts:[],activities:[],opportunities:[],quotes:[]}
const options={customers:[],owners:[],materials:[]}
const importRows=[{customer_id:4,name:'王女士',job_title:'采购',phone:'100',email:'',note:'重点客户'}]
const opportunityRows=[{customer_id:4,title:'新设备',owner_id:2,estimated_amount:'1200.50',expected_close_date:'2030-01-31',contact_id:null,note:''}]
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve}}
function fixture(t,callApi,perform=run=>run()){
  const previous=globalThis.window;t.after(()=>{globalThis.window=previous})
  globalThis.window={nexora:{callApi}}
  const state=createAppState();state.user.value={id:1,permissions}
  return {state,actions:createCrmActions(state,perform)}
}

test('联系人 CSV 保留带引号的逗号并拒绝越界或错列',()=>{
  assert.deepEqual(parseContactCsv('\uFEFF客户编号,联系人姓名,职务,电话,邮箱,备注\r\n4,"王,女士",采购,100,,"备注""甲"""\r\n'),
    [{customer_id:4,name:'王,女士',job_title:'采购',phone:'100',email:'',note:'备注"甲"'}])
  assert.deepEqual(parseContactCsv('customer_id,name\n4,王女士'),
    [{customer_id:4,name:'王女士',job_title:'',phone:'',email:'',note:''}])
  assert.deepEqual(parseContactCsvBytes(new TextEncoder().encode('customer_id,name\n4,王女士').buffer),
    parseContactCsv('customer_id,name\n4,王女士'))
  assert.throws(()=>parseContactCsvBytes(Uint8Array.from([0xff,0xfe]).buffer))
  for(const csv of ['name,customer_id\n王女士,4','客户编号,联系人姓名\n0,王女士',
    '客户编号,联系人姓名\n4,"未闭合','客户编号,联系人姓名\n4,王女士,多余列',
    '客户编号,联系人姓名\n4,王女士\n\n5,李女士','客户编号,联系人姓名\n']){
    assert.throws(()=>parseContactCsv(csv))
  }
})

test('联系人导入 IPC 限定字段并核对服务端响应',async t=>{
  const old=globalThis.fetch;t.after(()=>{globalThis.fetch=old});const requests=[]
  globalThis.fetch=async(url,config)=>{
    const path=new URL(url).pathname,body=config.body?JSON.parse(config.body):null
    requests.push({path,body})
    const output=path.endsWith('/login')?{token:'test',user:{id:1}}
      :path.endsWith('/import-preview')?{rows:body.rows.map((row,index)=>({
        row:index+1,customer_id:row.customer_id,customer_name:'客户甲',name:row.name,
        existing_contact_ids:[],batch_rows:[],requires_confirmation:false})),requires_confirmation:false}
      :{batch_reference:'0123456789abcdef',created:body.rows.map((row,index)=>({
        id:index+1,customer_id:row.customer_id,name:row.name,version:1}))}
    return new Response(JSON.stringify(output),{status:200})
  }
  await callBackend('login',{});requests.length=0
  await callBackend('contactImportPreview',{rows:[{...importRows[0],is_active:false,created_by:99}],path:'/users'})
  await callBackend('importContacts',{rows:importRows,reason:' 原名单核对 ',allow_similar:true,path:'/users'})
  assert.deepEqual(requests,[
    {path:'/api/v1/crm/contacts/import-preview',body:{rows:importRows}},
    {path:'/api/v1/crm/contacts/import',body:{rows:importRows,reason:'原名单核对',allow_similar:true}}
  ])
  for(const rows of [[],[{...importRows[0],customer_id:'4/../../users'}],
    [{...importRows[0],name:' '}],Array(101).fill(importRows[0])]){
    await assert.rejects(callBackend('contactImportPreview',{rows}),/联系人导入|编号无效/)
  }
  assert.equal(requests.length,2)
  const preview={rows:[{row:1,customer_id:4,customer_name:'客户甲',name:'王女士',
    existing_contact_ids:[],batch_rows:[],requires_confirmation:false}],requires_confirmation:false}
  validateContactImportPreview(preview,importRows)
  validateContactImportResult({batch_reference:'0123456789abcdef',created:[{id:1,customer_id:4,name:'王女士',version:1}]},importRows)
  assert.throws(()=>validateContactImportPreview({...preview,rows:[{...preview.rows[0],customer_id:5}]},importRows))
  assert.throws(()=>validateContactImportResult({batch_reference:'0123456789abcdef',created:[{id:1,customer_id:5,name:'王女士',version:1}]},importRows))
})

test('联系人导入写入成功后即使刷新失败也不提示重复提交',async t=>{
  const calls=[];const {state,actions}=fixture(t,async(action,data)=>{
    calls.push([action,data]);if(action==='importContacts')return {created:[{id:9}]}
    throw Error('刷新失败')
  })
  assert.equal(await actions.importContactRows(importRows,'资料核对',false),true)
  assert.deepEqual(calls[0],['importContacts',{rows:importRows,reason:'资料核对',allow_similar:false}])
  state.user.value={id:2,permissions:['crm.view']}
  assert.equal(await actions.importContactRows(importRows,'资料核对',false),false)
  assert.equal(calls.length,4)
})

test('商机 CSV 校验列、编号、金额、日期与 UTF-8',()=>{
  const compact='customer_id,title,owner_id,estimated_amount,expected_close_date\n4,新设备,2,1200.50,2030-01-31'
  assert.deepEqual(parseOpportunityCsv(compact),opportunityRows)
  assert.deepEqual(parseOpportunityCsvBytes(new TextEncoder().encode(compact).buffer),opportunityRows)
  assert.deepEqual(parseOpportunityCsv('\uFEFF客户编号,商机名称,负责人编号,预计金额,预计成交日期,联系人编号,备注\r\n4,"新,设备",2,0,2030-01-31,6,"备注""甲"""\r\n'),
    [{customer_id:4,title:'新,设备',owner_id:2,estimated_amount:'0',expected_close_date:'2030-01-31',contact_id:6,note:'备注"甲"'}])
  assert.throws(()=>parseOpportunityCsvBytes(Uint8Array.from([0xff,0xfe]).buffer))
  for(const line of ['0,新设备,2,1,2030-01-31','4,新设备,0,1,2030-01-31',
    '4,新设备,2,1.001,2030-01-31','4,新设备,2,1,2030-02-30',
    '4,"未闭合,2,1,2030-01-31','4,新设备,2,1,2030-01-31,多余列']){
    assert.throws(()=>parseOpportunityCsv(compact.split('\n')[0]+'\n'+line))
  }
  assert.throws(()=>parseOpportunityCsv(compact+'\n\n5,次商机,2,1,2030-01-31'))
})

test('商机导入 IPC 清理额外字段并校验预检和提交响应',async t=>{
  const old=globalThis.fetch;t.after(()=>{globalThis.fetch=old});const requests=[]
  globalThis.fetch=async(url,config)=>{
    const path=new URL(url).pathname,body=config.body?JSON.parse(config.body):null
    requests.push({path,body})
    const output=path.endsWith('/import-preview')?{rows:body.rows.map((row,index)=>({
      row:index+1,customer_id:row.customer_id,customer_name:'客户甲',title:row.title,
      owner_id:row.owner_id,owner_name:'销售员',contact_name:'',existing_opportunity_ids:[],batch_rows:[],requires_confirmation:false
    })),requires_confirmation:false}: {batch_reference:'0123456789abcdef',created:body.rows.map((row,index)=>({
      id:index+1,customer_id:row.customer_id,title:row.title,version:1}))}
    return new Response(JSON.stringify(output),{status:200})
  }
  await callBackend('opportunityImportPreview',{rows:[{...opportunityRows[0],stage:'won',created_by:99}],path:'/users'})
  await callBackend('importOpportunities',{rows:opportunityRows,reason:' 名单核对 ',allow_similar:true})
  assert.deepEqual(requests,[
    {path:'/api/v1/crm/opportunities/import-preview',body:{rows:opportunityRows}},
    {path:'/api/v1/crm/opportunities/import',body:{rows:opportunityRows,reason:'名单核对',allow_similar:true}}
  ])
  for(const rows of [[],[{...opportunityRows[0],owner_id:'2/../../users'}],
    [{...opportunityRows[0],estimated_amount:'1e3'}],Array(101).fill(opportunityRows[0])]){
    await assert.rejects(callBackend('opportunityImportPreview',{rows}),/商机导入|编号无效|金额无效/)
  }
  assert.equal(requests.length,2)
  const preview={rows:[{row:1,customer_id:4,customer_name:'客户甲',title:'新设备',owner_id:2,
    owner_name:'销售员',contact_name:'',existing_opportunity_ids:[],batch_rows:[],requires_confirmation:false}],requires_confirmation:false}
  validateOpportunityImportPreview(preview,opportunityRows)
  validateOpportunityImportResult({batch_reference:'0123456789abcdef',created:[{id:1,customer_id:4,title:'新设备',version:1}]},opportunityRows)
  assert.throws(()=>validateOpportunityImportPreview({...preview,rows:[{...preview.rows[0],owner_id:3}]},opportunityRows))
  assert.throws(()=>validateOpportunityImportResult({batch_reference:'0123456789abcdef',created:[{id:1,customer_id:5,title:'新设备',version:1}]},opportunityRows))
})

test('商机导入写入成功后刷新失败仍报告成功，撤权后阻止导入',async t=>{
  const calls=[];const {state,actions}=fixture(t,async(action,data)=>{
    calls.push([action,data]);if(action==='importOpportunities')return {created:[{id:9}]}
    throw Error('刷新失败')
  })
  assert.equal(await actions.importOpportunityRows(opportunityRows,'名单核对',false),true)
  assert.deepEqual(calls[0],['importOpportunities',{rows:opportunityRows,reason:'名单核对',allow_similar:false}])
  state.user.value={id:2,permissions:['crm.view']}
  assert.equal(await actions.importOpportunityRows(opportunityRows,'名单核对',false),false)
  assert.equal(calls.length,4)
})

test('CRM 入口不被普通销售查看权限放开，审核和转单按实际阶段授权',()=>{
  assert.equal(canVisitRoute(routeByKey('customerRelations'),['sales.view']),false)
  assert.equal(canVisitRoute(routeByKey('customerRelations'),['crm.view']),true)
  assert.deepEqual(quoteActions({...quote,status:'submitted'},['crm_quote.review'],1),[])
  assert.deepEqual(quoteActions({...quote,status:'submitted'},['crm_quote.review'],2),['approve','reject'])
  assert.deepEqual(quoteActions(quote,['crm_quote.convert'],2),[])
  assert.deepEqual(quoteActions(quote,permissions,2),['convert'])
  assert.deepEqual(quoteActions({...quote,opportunity_stage:'won'},permissions,2),[])
  assert.deepEqual(quoteActions({...quote,expired:true},permissions,2),[])
  assert.deepEqual(quoteActions({...quote,contact_active:false},permissions,2),[])
  assert.deepEqual(quoteActions({...quote,status:'submitted',contact_active:false},['crm_quote.review'],2),['reject'])
})

test('表单约束拒绝非法日期、精度、重复行和不完整归属',()=>{
  const forms=emptyCrmForms();forms.quote=structuredClone(quoteInput)
  assert.equal(crmFormError('quote',forms),'')
  for(const patch of [{valid_until:'2030-02-30'},{reference:' '},{opportunity_id:0},
    {lines:[{...quoteInput.lines[0],quantity:'0'}]},{lines:[{...quoteInput.lines[0],unit_price:'1e3'}]},
    {lines:[{...quoteInput.lines[0],unit_price:'0.00001'}]},{lines:[quoteInput.lines[0],quoteInput.lines[0]]}]){
    assert.ok(crmFormError('quote',{...forms,quote:{...quoteInput,...patch}}))
  }
  assert.ok(crmFormError('contact',forms));assert.ok(crmFormError('activity',forms));assert.ok(crmFormError('opportunity',forms))
  forms.opportunity={customer_id:1,contact_id:null,title:'设备',owner_id:1,stage:'qualified',estimated_amount:'1.001',probability_percent:null,expected_close_date:'2030-01-31',note:''}
  assert.ok(crmFormError('opportunity',forms));forms.opportunity.estimated_amount='100.01';assert.equal(crmFormError('opportunity',forms),'')
  for(const invalid of [-1,101,1.5,NaN]){forms.opportunity.probability_percent=invalid;assert.match(crmFormError('opportunity',forms),/成交概率/)}
  forms.opportunity.probability_percent=0;assert.equal(crmFormError('opportunity',forms),'')
  assert.ok(crmSnapshotRows('quote',{...quote,party:{customer_name:'固定客户',contact_name:'王女士'}}).some(row=>row.label==='报价客户' && row.value==='固定客户'))
})

test('IPC 白名单阻止路径注入、状态和金额伪造，清除表格内部行标记',async t=>{
  const old=globalThis.fetch;t.after(()=>{globalThis.fetch=old});const requests=[]
  globalThis.fetch=async(url,config)=>{requests.push({path:new URL(url).pathname,method:config.method,body:config.body?JSON.parse(config.body):null});
    return new Response(JSON.stringify(new URL(url).pathname.endsWith('/login')?{token:'test',user:{id:1}}:{}),{status:200})}
  await callBackend('login',{});requests.length=0
  await callBackend('saveCrmQuote',{...quoteInput,status:'approved',customer_id:22,total_amount:'0',lines:quoteInput.lines.map(row=>({...row,_X_ROW_KEY:'ui',line_total:'0'}))})
  assert.deepEqual(requests[0],{path:'/api/v1/crm/quotes',method:'POST',body:quoteInput})
  await callBackend('convertCrmQuote',{id:1,version:3,opportunity_version:2,reason:'转单',acceptance_reference:'客户邮件',lines:[],total_amount:'0'})
  assert.deepEqual(requests[1].body,{version:3,opportunity_version:2,reason:'转单',acceptance_reference:'客户邮件'})
  for(const id of [true,0,1.2,'1/../../users'])await assert.rejects(callBackend('crmDetail',{kind:'quote',id}),/编号无效/)
  await assert.rejects(callBackend('crmDetail',{kind:'quote/../../roles',id:1}),/类型无效/)
  await assert.rejects(callBackend('changeCrmQuote',{id:1,version:3,action:'post'}),/不允许/)
  await assert.rejects(callBackend('closeCrmActivity',{id:1,version:1,action:'convert'}),/不允许/)
  await assert.rejects(callBackend('saveCrmQuote',{...quoteInput,lines:null}),/明细无效/)
  assert.equal(requests.length,2)
})

test('报价 PDF 只走固定路径，核对文件格式与会话边界',async t=>{
  const previous=globalThis.fetch;t.after(()=>{globalThis.fetch=previous})
  const requests=[];let contentType='application/pdf';let content='%PDF-1.7\n报价内容\n%%EOF'
  globalThis.fetch=async(url,config)=>{
    const path=new URL(url).pathname
    requests.push({path,authorization:config.headers.Authorization})
    if(path.endsWith('/login'))return new Response(JSON.stringify({token:'pdf-token',user:{id:1}}))
    if(path.endsWith('/logout'))return new Response('{}')
    return new Response(content,{headers:{'content-type':contentType}})
  }
  await callBackend('login',{})
  const file=await fetchCrmQuotePdf(7)
  assert.equal(file.id,7)
  assert.deepEqual(requests.at(-1),{path:'/api/v1/crm/quotes/7/pdf',authorization:'Bearer pdf-token'})
  assert.equal(file.isCurrent(),true)
  assert.equal(file.bytes.toString(),content)
  for(const id of [0,true,1.5,'7/../../users'])await assert.rejects(fetchCrmQuotePdf(id),/编号无效/)
  assert.equal(requests.length,2)
  contentType='text/html'
  await assert.rejects(fetchCrmQuotePdf(7),/文件格式无效/)
  contentType='application/pdf';content='not a pdf'
  await assert.rejects(fetchCrmQuotePdf(7),/文件格式无效/)
  content='%PDF-'+'.'.repeat(5_000_000)+'%%EOF'
  await assert.rejects(fetchCrmQuotePdf(7),/大小限制/)
  await callBackend('logout',undefined)
  assert.equal(file.isCurrent(),false)
  await assert.rejects(fetchCrmQuotePdf(7),/请先登录/)
})

test('报价 PDF 保存只对已批准记录开放，取消或换号不显示成功',async t=>{
  const {state,actions}=fixture(t,()=>Promise.resolve({}))
  const saved=[]
  globalThis.window.nexora.saveCrmQuotePdf=async id=>{saved.push(id);return null}
  assert.equal(await actions.exportCrmQuotePdf({...quote,status:'draft'}),false)
  assert.equal(saved.length,0)
  assert.equal(await actions.exportCrmQuotePdf(quote),false)
  assert.deepEqual(saved,[1])
  assert.equal(state.notice.value,'')
  globalThis.window.nexora.saveCrmQuotePdf=async id=>{saved.push(id);return `quote-${id}.pdf`}
  assert.equal(await actions.exportCrmQuotePdf(quote),true)
  assert.match(state.notice.value,/已保存固定报价 PDF/)
  const pending=deferred()
  globalThis.window.nexora.saveCrmQuotePdf=()=>pending.promise
  const old=actions.exportCrmQuotePdf(quote)
  state.user.value={id:2,permissions:['crm.view']};pending.resolve('old.pdf')
  assert.equal(await old,false)
  state.user.value={id:3,permissions:[]}
  assert.equal(await actions.exportCrmQuotePdf(quote),false)
})

test('商机预测 IPC 限定概率并校验服务端汇总',async t=>{
  const old=globalThis.fetch;t.after(()=>{globalThis.fetch=old});const requests=[]
  const forecast={currency:'CNY',rated_count:1,unrated_count:2,estimated_amount:'100.01',weighted_amount:'50.01',
    rows:[{id:1,customer_id:2,customer_name:'客户甲',title:'项目',owner_name:'销售员',stage:'prospect',
      expected_close_date:'2030-01-31',estimated_amount:'100.01',probability_percent:50,weighted_amount:'50.01',overdue:false}]}
  globalThis.fetch=async(url,config)=>{const path=new URL(url).pathname;requests.push({path,body:config.body?JSON.parse(config.body):null});
    return new Response(JSON.stringify(path.endsWith('/login')?{token:'test',user:{id:1}}:path.endsWith('/forecast')?forecast:{}),{status:200})}
  await callBackend('login',{});requests.length=0
  const input={customer_id:2,contact_id:null,title:'项目',owner_id:1,stage:'prospect',estimated_amount:'100.01',
    probability_percent:50,expected_close_date:'2030-01-31',note:''}
  await callBackend('saveCrmOpportunity',{...input,created_by:99,weighted_amount:'0.00'})
  assert.deepEqual(requests[0],{path:'/api/v1/crm/opportunities',body:input})
  for(const probability_percent of [-1,101,1.5,'50',true])await assert.rejects(
    callBackend('saveCrmOpportunity',{...input,probability_percent}),/成交概率/)
  assert.deepEqual(await callBackend('crmForecast',undefined),forecast)
  validateCrmForecast(forecast)
  assert.throws(()=>validateCrmForecast({...forecast,rows:[{...forecast.rows[0],probability_percent:101}]}))
  assert.throws(()=>validateCrmForecast({...forecast,rated_count:2}))
  assert.equal(requests.length,2)
})

test('客户负责人分配只转发白名单字段，编号和版本须为正整数',async t=>{
  const old=globalThis.fetch;t.after(()=>{globalThis.fetch=old});const requests=[]
  globalThis.fetch=async(url,config)=>{requests.push({path:new URL(url).pathname,method:config.method,
    body:config.body?JSON.parse(config.body):null});return new Response('{}',{status:200})}
  await callBackend('assignCustomerOwner',{id:4,owner_id:7,version:2,reason:'交接依据',is_admin:true})
  await callBackend('customerOwnerChanges',{id:4})
  assert.deepEqual(requests[0],{path:'/api/v1/customers/4/owner',method:'PUT',
    body:{owner_id:7,version:2,reason:'交接依据'}})
  assert.deepEqual(requests[1],{path:'/api/v1/customers/4/owner-changes',method:'GET',body:null})
  for(const id of [0,true,'4/../../users'])await assert.rejects(
    callBackend('assignCustomerOwner',{id,owner_id:7,version:2,reason:'交接'}),/编号无效/)
  await assert.rejects(callBackend('assignCustomerOwner',{id:4,owner_id:7,version:0,reason:'交接'}),/编号无效/)
  assert.equal(requests.length,2)
})

test('归属变更刷新 CRM 并读取历史，旧账号迟到记录不会覆盖新账号',async t=>{
  const pending=deferred();const calls=[]
  const {state,actions}=fixture(t,async(action,data)=>{calls.push([action,data]);
    if(action==='customerOwnerChanges')return pending.promise
    return action==='crmOptions'?options:action==='crmOverview'?overview:{id:4,owner_id:2,version:3}})
  state.user.value={id:1,permissions:[...permissions,'customer.assign']}
  const old=actions.loadCustomerOwnerChanges(4)
  state.user.value={id:2,permissions:['crm.view']};pending.resolve([{id:1}])
  assert.equal(await old,false);assert.deepEqual(state.crmOwnerChanges.value,[])
  assert.equal(await actions.assignCustomerOwner(4,2,2,'转交'),false)
  state.user.value={id:1,permissions:[...permissions,'customer.assign']}
  assert.equal(await actions.assignCustomerOwner(4,2,2,'转交'),true)
  assert.ok(calls.some(([action,data])=>action==='assignCustomerOwner' && data.version===2))
  assert.ok(calls.some(([action])=>action==='crmOverview'))
})

test('较旧详情、迟到错误和关闭后的结果不能覆盖当前记录',async t=>{
  const pending=deferred();const {state,actions}=fixture(t,(action,data)=>data.id===1?pending.promise:Promise.resolve(action==='crmDetail'?{id:2}:[]))
  const first=actions.loadCrmDetail('quote',1);assert.equal(await actions.loadCrmDetail('contact',2),true)
  pending.resolve({id:1});assert.equal(await first,false);assert.equal(state.crmDetail.value.kind,'contact');assert.equal(state.crmDetail.value.record.id,2)
  const late=deferred();globalThis.window.nexora.callApi=()=>late.promise
  const read=actions.loadCrmDetail('quote',3);actions.clearCrmDetail();late.resolve(quote)
  assert.equal(await read,false);assert.equal(state.crmDetail.value,null)
})

test('断线作废敏感资料但保留全部输入，换号撤权后清除表单',async t=>{
  const pending=deferred();const {state,actions}=fixture(t,()=>pending.promise)
  state.crmForms.value.quote=structuredClone(quoteInput);state.crmEdit.value={quote:{kind:'quote',id:1,version:3,reason:'更正'}}
  const read=actions.loadCrm();state.connectionLost.value=true;pending.resolve(options)
  assert.equal(await read,false);assert.equal(state.crmOverview.value,null);assert.equal(state.crmForms.value.quote.reference,'Q-1')
  state.user.value={id:2,permissions:['crm.view']}
  assert.equal(state.crmForms.value.quote.reference,'');assert.deepEqual(state.crmEdit.value,{})
})

test('保存冲突保留输入、修订原因和行标记，成功后清空且读取证据',async t=>{
  const calls=[];let fail=true
  const {state,actions}=fixture(t,async(action,data)=>{calls.push([action,data]);if(action==='saveCrmQuote'){if(fail)throw Error('版本冲突');return {...quote,id:9}}
    return action==='crmOptions'?options:action==='crmOverview'?overview:action==='crmChanges'?[]:{...quote,id:9}},async run=>{try{await run()}catch{}})
  state.crmForms.value.quote={...structuredClone(quoteInput),lines:quoteInput.lines.map(row=>({...row,_X_ROW_KEY:'ui'}))}
  state.crmEdit.value={quote:{kind:'quote',id:1,version:3,reason:'价格修订'}}
  assert.equal(await actions.saveCrm('quote'),false);assert.equal(state.crmForms.value.quote.reference,'Q-1');assert.equal(state.crmEdit.value.quote.reason,'价格修订')
  assert.deepEqual(calls[0][1],{...quoteInput,id:1,version:3,reason:'价格修订'})
  fail=false;assert.equal(await actions.saveCrm('quote'),true);assert.equal(state.crmForms.value.quote.reference,'');assert.equal(state.crmDetail.value.record.id,9)
})

test('新建联系人固定启用，失败保留草稿；修订可按原版本停用',async t=>{
  const calls=[];let fail=true
  const contact={id:9,version:2,customer_id:4,name:'王女士',is_active:true}
  const {state,actions}=fixture(t,async(action,data)=>{
    if(action==='saveCrmContact'){calls.push(data);if(fail)throw Error('保存失败');return {...contact,...data}}
    return action==='crmOptions'?options:action==='crmOverview'?overview:action==='crmChanges'?[]:contact
  },async run=>{try{await run()}catch{}})
  // 历史草稿即使残留停用值，新建请求仍按隐藏字段的默认规则启用。
  const draft={customer_id:4,name:'王女士',job_title:'采购',phone:'100',email:'',note:'重点客户',is_active:false}
  state.crmForms.value.contact={...draft}
  assert.equal(await actions.saveCrm('contact'),false)
  assert.equal(calls[0].is_active,true)
  assert.deepEqual(state.crmForms.value.contact,draft)
  fail=false
  assert.equal(await actions.saveCrm('contact'),true)
  assert.equal(calls[1].is_active,true)
  assert.equal(state.crmForms.value.contact.name,'')
  state.crmForms.value.contact={...draft}
  state.crmEdit.value.contact={kind:'contact',id:9,version:2,reason:'已离职'}
  assert.equal(await actions.saveCrm('contact'),true)
  assert.deepEqual(calls[2],{...draft,id:9,version:2,reason:'已离职'})
})

test('旧会话保存结束不能清除新账号草稿；未发出的旧保存不能使用新会话',async t=>{
  const pending=deferred();const {state,actions}=fixture(t,()=>pending.promise)
  state.crmForms.value.quote=structuredClone(quoteInput);const write=actions.saveCrm('quote')
  state.user.value={id:2,permissions};state.crmForms.value.quote.reference='新账号草稿';pending.resolve(quote)
  assert.equal(await write,false);assert.equal(state.crmForms.value.quote.reference,'新账号草稿')
  const gate=deferred();let called=false
  const delayed=fixture(t,()=>{called=true;return Promise.resolve(quote)},async run=>{await gate.promise;await run()})
  const oldWrite=delayed.actions.saveCrm('quote');delayed.state.user.value={id:3,permissions};gate.resolve()
  assert.equal(await oldWrite,false);assert.equal(called,false)
})

test('只读 CRM 可读资料证据，缺少原单权限不能转单',async t=>{
  const calls=[];const {state,actions}=fixture(t,async action=>{calls.push(action);return action==='crmOptions'?options:overview})
  state.user.value={id:2,permissions:['crm.view']}
  assert.equal(await actions.loadCrm(),true);assert.equal(await actions.saveCrm('contact'),false)
  assert.equal(await actions.changeCrmQuote(quote,'approve','核对'),false)
  assert.equal(await actions.closeCrmActivity({id:1,version:1},'complete','完成'),false)
  state.user.value={id:2,permissions:['crm.view','crm_quote.convert']}
  assert.equal(await actions.convertCrmQuote(quote,'接受依据','转单'),false)
  assert.deepEqual(calls,['crmOptions','crmOverview','crmForecast'])
})

test('详情读取失败保留编辑表单并提供错误，不打开过期记录编辑',async t=>{
  const {state,actions}=fixture(t,()=>Promise.reject(Error('读取失败')))
  state.crmForms.value.contact.name='未保存联系人'
  assert.equal(await actions.editCrm('contact',1),false);assert.deepEqual(state.crmEdit.value,{})
  assert.equal(state.crmForms.value.contact.name,'未保存联系人');assert.match(state.crmError.value,/读取失败/)
})

test('跨类型新建及保存保留其他修订的原版本，显式同类新建清空旧编辑',async t=>{
  const calls=[];const {state,actions}=fixture(t,async(action,data)=>{calls.push([action,data]);
    return action==='crmOptions'?options:action==='crmOverview'?overview:action==='crmChanges'?[]:{...quote,id:9}})
  state.crmForms.value.quote=structuredClone(quoteInput)
  state.crmEdit.value.quote={kind:'quote',id:1,version:3,reason:'价格修订'}
  state.crmForms.value.contact.name='另一个联系人草稿'
  actions.startNewCrm('contact')
  assert.equal(state.crmForms.value.contact.name,'另一个联系人草稿')
  assert.equal(state.crmEdit.value.quote.version,3)
  await actions.saveCrm('contact')
  assert.equal(state.crmEdit.value.quote.reason,'价格修订')
  await actions.saveCrm('quote')
  assert.deepEqual(calls.find(([action])=>action==='saveCrmQuote')[1],{...quoteInput,id:1,version:3,reason:'价格修订'})
  assert.deepEqual(state.crmEdit.value,{})
  state.crmForms.value.quote=structuredClone(quoteInput)
  state.crmEdit.value.quote={kind:'quote',id:1,version:3,reason:'旧修订'}
  actions.startNewCrm('quote')
  assert.equal(state.crmForms.value.quote.reference,'');assert.deepEqual(state.crmEdit.value,{})
})

test('已关闭商机的旧草稿不可进入修订，原未保存输入保留',async t=>{
  const {state,actions}=fixture(t,action=>Promise.resolve(action==='crmChanges'?[]:{...quote,status:'draft',opportunity_stage:'won'}))
  state.crmForms.value.quote.reference='未保存报价'
  assert.equal(await actions.editCrm('quote',1),false)
  assert.equal(state.crmForms.value.quote.reference,'未保存报价');assert.deepEqual(state.crmEdit.value,{})
})
