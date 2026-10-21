import assert from 'node:assert/strict'
import { test } from 'node:test'
import { crmCustomerRows, selectCrmFormCustomer } from '../src/renderer/src/views/workspace/sales/crm-customers.ts'
import { emptyCrmForms } from '../src/renderer/src/store/modules/crm-actions.ts'
import { crmFormError, quoteActions } from '../src/renderer/src/views/workspace/sales/crm-display.ts'
import { callBackend } from '../src/main/backend.ts'

// 聚合只使用授权客户，完成记录和停用联系人不计入当前待办。
test('客户列表聚合联系人、待跟进与最近期限，不泄露范围外的旧缓存', () => {
  const options = {customers:[{id:1,name:'客户甲',owner_id:2,version:1}],owners:[{id:2,name:'负责人'}],materials:[]}
  const overview = {contacts:[{id:1,customer_id:1,is_active:1},{id:2,customer_id:1,is_active:0},{id:3,customer_id:9,is_active:1}],
    activities:[{id:1,customer_id:1,status:'planned',due_date:'2030-02-01',overdue:false},
      {id:2,customer_id:1,status:'planned',due_date:'2029-12-01',overdue:true},
      {id:3,customer_id:1,status:'completed',due_date:'2029-01-01',overdue:false},
      {id:4,customer_id:9,status:'planned',due_date:'2029-01-01',overdue:true}],opportunities:[],quotes:[]}
  const [row] = crmCustomerRows(options,overview)
  assert.equal(row.contact_count,1);assert.equal(row.contacts.length,2)
  assert.equal(row.pending_count,2);assert.equal(row.overdue_count,1);assert.equal(row.next_followup.id,2)
  assert.equal(row.owner_name,'负责人');assert.equal(crmCustomerRows(options,overview).length,1)
  assert.deepEqual(crmCustomerRows(null,overview),[])
  assert.equal(crmCustomerRows({...options,owners:[]},overview)[0].owner_name,'账号 #2')
})

test('从其他客户发起跟进或报价清除旧关联，同客户的未保存正文保持原样', () => {
  const forms=emptyCrmForms()
  forms.quote={...forms.quote,customer_id:1,contact_id:2,opportunity_id:3,terms:'未保存条款'}
  selectCrmFormCustomer(forms,'quote',1)
  assert.equal(forms.quote.opportunity_id,3)
  selectCrmFormCustomer(forms,'quote',4)
  assert.equal(forms.quote.customer_id,4);assert.equal(forms.quote.contact_id,null);assert.equal(forms.quote.opportunity_id,null)
  assert.equal(forms.quote.terms,'未保存条款')
  forms.activity={...forms.activity,customer_id:1,opportunity_id:3,contact_id:2,subject:'原跟进正文'}
  selectCrmFormCustomer(forms,'activity',4)
  assert.equal(forms.activity.opportunity_id,null);assert.equal(forms.activity.contact_id,null)
  assert.equal(forms.activity.subject,'原跟进正文')
})

test('客户直接报价无需商机也可校验和转单，权限、有效期与审批仍约束动作', () => {
  const forms=emptyCrmForms()
  forms.quote={customer_id:1,opportunity_id:null,contact_id:null,reference:'直接报价',valid_until:'2030-01-01',terms:'',lines:[{material_id:1,quantity:'1',unit_price:'10'}]}
  assert.equal(crmFormError('quote',forms),'')
  const quote={status:'approved',approval:{status:'approved'},opportunity_id:null,opportunity_stage:null,expired:false,contact_active:true}
  const permissions=['crm_quote.convert','sales_order.create']
  assert.deepEqual(quoteActions(quote,permissions,1),['convert'])
  for(const patch of [{expired:true},{contact_active:false},{approval:{status:'submitted'}}])assert.deepEqual(quoteActions({...quote,...patch},permissions,1),[])
  assert.deepEqual(quoteActions(quote,['crm_quote.convert'],1),[])
})

test('直接报价 IPC 保留客户和空商机版本，拒绝伪造客户编号和金额', async t => {
  const old=globalThis.fetch;t.after(()=>{globalThis.fetch=old})
  const requests=[]
  globalThis.fetch=async(url,config)=>{
    requests.push({path:new URL(url).pathname,body:config.body?JSON.parse(config.body):null})
    return new Response(JSON.stringify(new URL(url).pathname.endsWith('/login')?{token:'test',user:{id:1}}:{}),{status:200})
  }
  await callBackend('login',{});requests.length=0
  const input={customer_id:1,opportunity_id:null,contact_id:null,reference:'Q',valid_until:'2030-01-01',terms:'',lines:[{material_id:1,quantity:'1',unit_price:'10'}]}
  await callBackend('saveCrmQuote',{...input,total_amount:'0',status:'approved'})
  assert.deepEqual(requests[0].body,input)
  await callBackend('convertCrmQuote',{id:1,version:3,opportunity_version:null,reason:'客户接受',acceptance_reference:'邮件'})
  assert.equal(requests[1].body.opportunity_version,null)
  await assert.rejects(callBackend('saveCrmQuote',{...input,customer_id:'1/../2'}),/编号无效/)
  assert.equal(requests.length,2)
})
