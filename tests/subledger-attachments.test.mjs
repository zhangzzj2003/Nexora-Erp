import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createHash} from 'node:crypto'
import {readFile} from 'node:fs/promises'
import vm from 'node:vm'
import ts from 'typescript'
import {callBackend,fetchSubledgerAttachment} from '../src/main/backend.ts'
import {createAppState} from '../src/renderer/src/store/state.ts'
import {createSubledgerAttachmentActions} from '../src/renderer/src/store/modules/subledger-attachment-actions.ts'
import {validateSubledgerAttachmentResult} from '../src/shared/subledger-attachment-validation.ts'

const pdf=Buffer.from('%PDF-1.4\n<<>>\n%%EOF\n'), sha=createHash('sha256').update(pdf).digest('hex')
const source={id:4,opening_id:7,opening_version:2,opening_balance_id:1,ledger_opening_version:4,effective_date:'2026-01-01',currency:'CNY',
  kind:'receivable',party_id:1,party_name:'客户甲',account_id:1,account_code:'AR',account_name:'应收',document_reference:'OLD-A',document_date:'2025-12-01',
  debit:'100.00',credit:'0.00',auxiliary:[{kind:'customer',id:1,code:'customer:1',name:'客户甲'}]}
const item={id:9,opening_id:7,source,source_status:'matched',current_line_id:4,approved_original:false,can_reverse:true,
  file_name:'原单.pdf',media_type:'application/pdf',byte_count:pdf.length,sha256:sha,reason:'原件',created_by:1,created_by_name:'admin',created_at:'2026-10-09 01:00:00',reversal:null}
const page={opening_id:7,opening_version:2,opening_status:'draft',can_modify:true,page:1,page_size:50,total:1,active_count:1,changed_count:0,lines:[source],items:[item]}

test('原单附件固定路径、版本及原单白名单在网络前校验',async t=>{
  const old=process.env.NEXORA_API_URL
  t.after(()=>{if(old===undefined)delete process.env.NEXORA_API_URL;else process.env.NEXORA_API_URL=old})
  process.env.NEXORA_API_URL='http://127.0.0.1:8123'
  const calls=[]
  t.mock.method(globalThis,'fetch',async(url,options)=>{
    calls.push({path:url.pathname+url.search,method:options.method,body:options.body})
    if(url.pathname.endsWith('/login'))return Response.json({token:'subledger-files',user:{id:1}})
    if(url.pathname.endsWith('/reverse'))return Response.json({...item,can_reverse:false,reversal:{id:1,reason:'更正',created_by:1,created_by_name:'admin',created_at:item.created_at}})
    return Response.json(options.method==='GET'?page:item)
  })
  await callBackend('login',{})
  await callBackend('subledgerAttachments',{id:7,page:1,page_size:50,path:'/users'})
  assert.equal(calls.at(-1).path,'/api/v1/finance/subledger-openings/7/attachments?page=1&page_size=50')
  const input={id:7,opening_version:2,line_id:4,file_name:'原单.pdf',content_base64:pdf.toString('base64'),reason:'原件'}
  await callBackend('addSubledgerAttachment',{...input,path:'/etc/passwd',source:{kind:'forged'}})
  const {id,...body}=input
  assert.deepEqual(JSON.parse(calls.at(-1).body),body)
  await callBackend('reverseSubledgerAttachment',{id:7,opening_version:2,attachmentId:9,reason:'更正',path:'/users'})
  assert.deepEqual(JSON.parse(calls.at(-1).body),{opening_version:2,reason:'更正'})
  const before=calls.length
  for(const mutation of [{opening_version:true},{line_id:'../users'},{id:0},{file_name:'../bad.pdf'},{content_base64:'bad%'},{reason:' '}]) {
    await assert.rejects(callBackend('addSubledgerAttachment',{...input,...mutation}))
  }
  await assert.rejects(callBackend('subledgerAttachments',{id:7,page:1,page_size:101}))
  assert.equal(calls.length,before)
})

test('原单附件响应拒绝跨方案、缺失来源、矛盾权限、旧版本和原文字节',()=>{
  validateSubledgerAttachmentResult('subledgerAttachments',page,7)
  for(const changed of [{opening_id:8},{opening_version:1},{changed_count:2},{page_size:true},{lines:[]},
    {items:[item,item]},{content_base64:'raw'},{items:[{...item,source:{...source,opening_id:8}}]},
    {items:[{...item,source_status:'missing',current_line_id:4}]},{items:[{...item,approved_original:true}]},
    {items:[{...item,sha256:'broken'}]},{items:[{...item,content:pdf}]}]) {
    assert.throws(()=>validateSubledgerAttachmentResult('subledgerAttachments',{...page,...changed},7),/附件响应无效/)
  }
  assert.throws(()=>validateSubledgerAttachmentResult('reverseSubledgerAttachment',item,7))
})

test('原件下载校验摘要、格式和会话，并使用固定分户路径',async t=>{
  const old=process.env.NEXORA_API_URL
  t.after(()=>{if(old===undefined)delete process.env.NEXORA_API_URL;else process.env.NEXORA_API_URL=old})
  process.env.NEXORA_API_URL='http://127.0.0.1:8123'
  let corrupt=false,token='a',requested
  t.mock.method(globalThis,'fetch',async url=>{
    if(url.pathname.endsWith('/login'))return Response.json({token,user:{id:1}})
    requested=url.pathname
    return new Response(pdf,{headers:{'content-type':'application/octet-stream','x-nexora-sha256':corrupt?'0'.repeat(64):sha,'x-nexora-file-extension':'.pdf'}})
  })
  await callBackend('login',{})
  const file=await fetchSubledgerAttachment(7,9)
  assert.equal(requested,'/api/v1/finance/subledger-openings/7/attachments/9')
  assert.deepEqual(file.bytes,pdf);assert.equal(file.isCurrent(),true)
  corrupt=true;await assert.rejects(fetchSubledgerAttachment(7,9),/校验失败/)
  token='b';await callBackend('login',{});assert.equal(file.isCurrent(),false)
})

test('附件操作隔离换号、撤权、证书变化及断开后重连的迟到结果',async t=>{
  const previous=globalThis.window;t.after(()=>{globalThis.window=previous})
  for(const mutation of [s=>{s.user.value.id=2},s=>{s.user.value.permissions=['subledger_opening.view']},
    s=>{s.server.value.fingerprint='other'},s=>{s.connectionLost.value=true;s.connectionLost.value=false}]) {
    const state=createAppState();state.user.value={id:1,roles:['finance'],permissions:['subledger_opening.view','subledger_opening.attachment']}
    state.server.value={id:'a',fingerprint:'a'}
    let resolve
    globalThis.window={nexora:{uploadSubledgerAttachment:()=>new Promise(r=>{resolve=r})}}
    const actions=createSubledgerAttachmentActions(state),pending=actions.uploadSubledgerAttachment(7,2,4,'原件')
    mutation(state);resolve(item);await assert.rejects(pending,/会话、权限或连接已变化/)
  }
  const state=createAppState();state.user.value={id:1,permissions:['subledger_opening.view']}
  let calls=0;globalThis.window={nexora:{uploadSubledgerAttachment:async()=>{calls++;return item}}}
  await assert.rejects(createSubledgerAttachmentActions(state).uploadSubledgerAttachment(7,2,4,'越权'))
  assert.equal(calls,0)
})

test('真实主进程文件处理器在对话框前验证来源，并隔离选择期间换号和文件变化',async()=>{
  const sourceText=await readFile(new URL('../src/main/index.ts',import.meta.url),'utf8')
  const code=sourceText.slice(sourceText.indexOf("  ipcMain.handle('subledger:upload-attachment'"),sourceText.indexOf("  ipcMain.handle('journal:upload-attachment'"))
  const handlers=new Map();let marker='a',picked=0,mutate=false,uploaded=0,exported=0
  const context={Buffer,ipcMain:{handle:(name,fn)=>handlers.set(name,fn)},assertMainWindow:()=>{},mainWindow:{},
    backendSessionMarker:()=>marker,dialog:{showOpenDialog:async()=>{picked++;if(mutate)marker='b';return {canceled:false,filePaths:['qa.pdf']}},
      showSaveDialog:async()=>({canceled:false,filePath:'saved.pdf'})},stat:async()=>({isFile:()=>true,size:pdf.length}),readFile:async()=>pdf,
    basename:x=>x,extname:x=>'.'+x.split('.').at(-1),callBackend:async(action,input)=>{uploaded++;assert.equal(input.opening_version,2);assert.equal(input.line_id,4);return item},
    fetchSubledgerAttachment:async()=>({openingId:7,attachmentId:9,extension:'.pdf',bytes:pdf,isCurrent:()=>true}),writeFile:async()=>{exported++}}
  vm.runInNewContext(ts.transpileModule(code,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.None}}).outputText,context)
  const upload=handlers.get('subledger:upload-attachment'),save=handlers.get('subledger:save-attachment')
  for(const args of [[7,true,4,'原件'],[7,2,'../users','原件'],[7,2,4,' ']])await assert.rejects(upload({},...args),/参数无效/)
  assert.equal(picked,0)
  assert.deepEqual(await upload({},7,2,4,'原件'),item);assert.equal(uploaded,1)
  mutate=true;await assert.rejects(upload({},7,2,4,'原件'),/会话已变化/);assert.equal(uploaded,1)
  assert.equal(await save({},7,9),true);assert.equal(exported,1)
  context.stat=async()=>({isFile:()=>true,size:6*1024*1024});mutate=false
  await assert.rejects(upload({},7,2,4,'原件'),/不超过 5 MiB/)
  context.stat=async()=>({isFile:()=>true,size:pdf.length});context.readFile=async()=>Buffer.alloc(0)
  await assert.rejects(upload({},7,2,4,'原件'),/大小已变化/)
})
