<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref,watch} from 'vue'
import {storeToRefs} from 'pinia'
import {NModal} from 'naive-ui'
import type {AfterSalesAction,AfterSalesEvidence,AfterSalesResponsibilityOutcome} from '../../../../../shared/after-sales-api'
import {usePiniaAppStore} from '../../../store/app-store'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import AfterSalesEditor from './AfterSalesEditor.vue'
import AfterSalesEvidenceView from './AfterSalesEvidence.vue'
import AfterSalesAttachments from './AfterSalesAttachments.vue'
import {afterSalesActions,afterSalesKind,afterSalesStatus,afterSalesCommand,afterSalesReversalHint} from './after-sales-display'
const store=usePiniaAppStore()
const {afterSalesOverview:overview,afterSalesDetail:detail,afterSalesLoading:loading,afterSalesError:failure,busy,user,connectionLost,error}=storeToRefs(store)
const mode=ref<'sources'|'records'>('sources'),editor=ref(false),query=ref(''),preparing=ref(false),reason=ref(''),evidence=ref(''),inspection=ref<'pass'|'fail'|''>('')
const command=ref<{row:AfterSalesEvidence;action:AfterSalesAction}|null>(null)
const laborCommand=ref<{row:AfterSalesEvidence;entryId:number|null}|null>(null),laborHours=ref('')
const responsibilityCommand=ref<AfterSalesEvidence|null>(null)
const responsibilityOutcome=ref<AfterSalesResponsibilityOutcome|''>(''),responsibilityBasis=ref('')
const disabled=computed(()=>busy.value||loading.value||preparing.value||connectionLost.value)
const sources=computed(()=>(overview.value?.sources??[]).filter(row=>[row.shipment_id,row.sales_order_id,row.customer_name,row.sku,row.material_name].join(' ').toLowerCase().includes(query.value.trim().toLowerCase())))
const records=computed(()=>(overview.value?.cases??[]).filter(row=>[row.reference,row.frozen_source.customer_name,row.frozen_source.sku,afterSalesKind[row.kind],afterSalesStatus[row.status]].join(' ').toLowerCase().includes(query.value.trim().toLowerCase())))
const sourceColumns=[{key:'source',title:'客户 / 原出库'},{key:'goods',title:'物品'},{key:'quantity',title:'原出库 / 剩余可办理'},{key:'actions',title:'操作'}]
const recordColumns=[{key:'source',title:'依据 / 客户'},{key:'plan',title:'方式 / 数量'},{key:'stage',title:'办理阶段'},{key:'actions',title:'操作 / 证据'}]
const actions=(row:AfterSalesEvidence)=>afterSalesActions(row,user.value?.permissions??[],user.value?.id??0)
function newRecord(id:number):void{if(!disabled.value&&store.startAfterSalesCase(id))editor.value=true}
async function editRecord(id:number):Promise<void>{if(disabled.value)return;preparing.value=true;try{if(await store.editAfterSalesCase(id))editor.value=true}finally{preparing.value=false}}
async function prepare(id:number,action:AfterSalesAction):Promise<void>{
  if(disabled.value)return;preparing.value=true;command.value=null;reason.value='';evidence.value='';inspection.value='';error.value=''
  try{if(await store.loadAfterSalesDetail(id)&&detail.value&&actions(detail.value).includes(action))command.value={row:detail.value,action}}finally{preparing.value=false}
}
async function execute():Promise<void>{if(command.value&&await store.changeAfterSalesCase(command.value.row,command.value.action,reason.value,evidence.value,inspection.value||undefined))command.value=null}
async function prepareLabor(entryId:number|null):Promise<void>{
  if(disabled.value||!detail.value||!store.can('after_sales.labor'))return
  const id=detail.value.id;preparing.value=true;laborCommand.value=null;laborHours.value='';reason.value='';evidence.value='';error.value=''
  try{
    if(await store.loadAfterSalesDetail(id)&&detail.value&&detail.value.kind==='repair'&&['received','repaired'].includes(detail.value.status)){
      const active=entryId===null||detail.value.labor.some(entry=>entry.id===entryId&&entry.action==='record'&&
        !detail.value!.labor.some(reverse=>reverse.original_id===entryId))
      if(active)laborCommand.value={row:detail.value,entryId}
    }
  }finally{preparing.value=false}
}
async function executeLabor():Promise<void>{
  if(!laborCommand.value)return
  const {row,entryId}=laborCommand.value
  const saved=entryId===null?await store.recordAfterSalesLabor(row,laborHours.value,reason.value,evidence.value)
    :await store.reverseAfterSalesLabor(row,entryId,reason.value,evidence.value)
  if(saved)laborCommand.value=null
}
function canAssess(row:AfterSalesEvidence):boolean{
  return store.can('after_sales.review')&&store.can('after_sales.view')&&
    !row.author_ids.includes(user.value?.id??0)&&['submitted','approved','processing','received','repaired','closed'].includes(row.status)
}
async function prepareResponsibility(id:number):Promise<void>{
  if(disabled.value)return
  preparing.value=true;responsibilityCommand.value=null;reason.value='';responsibilityOutcome.value='';responsibilityBasis.value='';error.value=''
  try{
    if(await store.loadAfterSalesDetail(id)&&detail.value&&canAssess(detail.value)){
      responsibilityCommand.value=detail.value
      responsibilityOutcome.value=detail.value.responsibility?.outcome??''
      responsibilityBasis.value=detail.value.responsibility?.basis??''
    }
  }finally{preparing.value=false}
}
async function executeResponsibility():Promise<void>{
  if(!responsibilityCommand.value||!responsibilityOutcome.value)return
  if(await store.assessAfterSalesResponsibility(responsibilityCommand.value,responsibilityOutcome.value,
    responsibilityBasis.value,reason.value))responsibilityCommand.value=null
}
function selectMode(value:'sources'|'records'):void{if(busy.value)return;mode.value=value;editor.value=false;query.value='';store.clearAfterSalesDetail()}
watch(()=>`${user.value?.id}:${user.value?.permissions.join('|')}`,()=>{command.value=null;laborCommand.value=null;responsibilityCommand.value=null;editor.value=false;if(!connectionLost.value&&store.can('after_sales.view'))void store.loadAfterSales()})
watch(connectionLost,()=>{command.value=null;laborCommand.value=null;responsibilityCommand.value=null;if(!connectionLost.value&&store.can('after_sales.view'))void store.loadAfterSales()})
onMounted(()=>{void store.loadAfterSales()});onUnmounted(()=>store.clearAfterSalesDetail())
</script>
<template>
  <section class="stack after-workspace">
    <div class="after-toolbar"><AppButton :variant="mode==='sources'?'primary':'secondary'" :disabled="busy" @click="selectMode('sources')">原出库来源</AppButton><AppButton :variant="mode==='records'?'primary':'secondary'" :disabled="busy" @click="selectMode('records')">售后记录</AppButton><AppButton :disabled="disabled" @click="store.loadAfterSales()">{{ loading?'正在读取…':'刷新来源与记录' }}</AppButton></div>
    <p v-if="connectionLost" role="alert">服务端连接中断，旧证据及动作已失效。同账号未保存输入保留，恢复连接后刷新并核对版本。</p>
    <p v-if="failure" role="alert">{{ failure }} 请刷新来源与记录后重试。</p>
    <AfterSalesEditor v-if="editor&&store.can('after_sales.create')" @close="editor=false" @saved="editor=false;mode='records'" />
    <template v-else>
      <WorkspaceTable v-if="mode==='sources'" title="售后出库来源" :show-title="false" :columns="sourceColumns" :data="sources" :min-table-width="1000" :loading="loading">
        <template #filters><label>搜索原出库<AppInput v-model="query" placeholder="客户、订单、出库或物料" /></label></template>
        <template #cell-source="{row}"><strong>{{ row.customer_name }}</strong><span class="after-secondary">出库 #{{ row.shipment_id }} · 订单 #{{ row.sales_order_id }}</span></template>
        <template #cell-goods="{row}">{{ row.sku }} · {{ row.material_name }}</template>
        <template #cell-quantity="{row}">原出库 {{ row.quantity }} {{ row.unit }}<span class="after-secondary">未退回且未占用 {{ row.remaining_quantity }} {{ row.unit }}</span></template>
        <template #cell-actions="{row}"><AppButton v-if="store.can('after_sales.create')" :disabled="disabled||Number(row.remaining_quantity)<=0" @click="newRecord(row.shipment_line_id)">编制售后</AppButton><span v-else>只读来源</span></template>
        <template #empty>没有可用的已确认出库来源，请先按销售流程交付；已冲销出库不能新增售后。</template>
      </WorkspaceTable>
      <WorkspaceTable v-else title="售后记录" :show-title="false" :columns="recordColumns" :data="records" :min-table-width="1100" :loading="loading">
        <template #filters><label>搜索售后<AppInput v-model="query" placeholder="售后编号、客户、物料、方式或阶段" /></label></template>
        <template #cell-source="{row}"><strong>{{ row.reference }}</strong><span class="after-secondary">{{ row.frozen_source.customer_name }} · 出库 #{{ row.frozen_source.shipment_id }}</span></template>
        <template #cell-plan="{row}">{{ afterSalesKind[row.kind as keyof typeof afterSalesKind] }} {{ row.quantity }} {{ row.frozen_source.unit }}<span v-if="row.kind==='repair'" class="after-secondary">{{ row.charge_mode==='free'?'明确免费维修':`整单服务费 ${row.fee_amount} 元` }}</span></template>
        <template #cell-stage="{row}">{{ afterSalesStatus[row.status as keyof typeof afterSalesStatus] }}<span class="after-secondary">v{{ row.version }} · {{ row.created_by_name }}</span></template>
        <template #cell-actions="{row}"><div class="after-toolbar"><AppButton :disabled="disabled" @click="store.loadAfterSalesDetail(row.id)">查看证据</AppButton><AppButton v-if="store.can('after_sales.create')&&['draft','rejected'].includes(row.status)" :disabled="disabled" @click="editRecord(row.id)">修订</AppButton><AppButton v-for="action in actions(row)" :key="action" :disabled="disabled" @click="prepare(row.id,action)">{{ afterSalesCommand[action] }}</AppButton></div></template>
        <template #empty>尚无售后记录。选择原出库编制申请，提交后独立审核。</template>
      </WorkspaceTable>
      <AfterSalesEvidenceView v-if="detail" :row="detail" />
      <AfterSalesAttachments v-if="detail" :case-id="detail.id" />
      <div v-if="detail&&canAssess(detail)" class="after-toolbar"><AppButton :disabled="disabled" @click="prepareResponsibility(detail.id)">{{ detail.responsibility?'更正责任核定':'登记责任核定' }}</AppButton></div>
      <div v-if="detail?.kind==='repair'&&['received','repaired'].includes(detail.status)&&store.can('after_sales.labor')" class="after-toolbar">
        <AppButton :disabled="disabled" @click="prepareLabor(null)">登记实际维修工时</AppButton>
        <AppButton v-for="entry in detail.labor.filter(item=>item.action==='record'&&!detail!.labor.some(reverse=>reverse.original_id===item.id))"
          :key="entry.id" :disabled="disabled" @click="prepareLabor(entry.id)">更正工时 #{{ entry.id }}</AppButton>
      </div>
    </template>
    <NModal :show="!!command" preset="card" :title="command?afterSalesCommand[command.action]:''" style="width:min(800px,calc(100vw - 48px));max-height:calc(100vh - 48px);overflow:auto" :mask-closable="!busy" :closable="!busy" @update:show="value=>{if(!value&&!busy)command=null}">
      <form v-if="command" class="after-operation" @submit.prevent="execute">
        <AfterSalesEvidenceView :row="command.row" compact />
        <p v-if="command.action==='process'">建立关联草稿后，退货须由仓库确认。换货销售订单在有效退货确认后才能继续；此操作不直接变动库存或金额。</p>
        <p v-if="command.action==='receive'">登记实际收到的客户物品；公司耗材另建其他出库草稿，须按原流程确认，不把客户物品记为公司入库。</p>
        <p v-if="command.action==='close'">依据实际交付结案。维修须先检验合格并交还客户；收费形成原订单维修应收，免费不形成收费来源。</p>
        <p v-if="command.action==='cancel'">已办理关联草稿须先取消；已收件维修须填写实际交还依据，已使用的公司耗材记录继续保留。</p>
        <p v-if="command.action==='reverse'">保留原结案及交接历史。{{ afterSalesReversalHint(command.row) }}</p>
        <label v-if="command.action==='inspect'">维修检验结果<WorkspaceSelect v-model="inspection" :options="[{label:'请选择检验结果',value:'',disabled:true},{label:'检验合格，可办理交还',value:'pass'},{label:'检验不合格，继续维修',value:'fail'}]" :disabled="busy" required /></label>
        <label>操作原因<AppInput v-model.trim="reason" maxlength="200" required :disabled="busy" /></label>
        <label>实际交接、检验或客户确认依据<AppInput v-model.trim="evidence" maxlength="400" :required="['receive','inspect','close'].includes(command.action)||(['received','repaired'].includes(command.row.status)&&command.action==='cancel')" :disabled="busy" /></label>
        <p v-if="error" role="alert">{{ error }} 原因和依据已保留；请重新加载最新证据后核对。</p>
        <div class="after-toolbar"><AppButton type="submit" variant="primary" :disabled="busy||connectionLost||!reason.trim()||(command.action==='inspect'&&!inspection)">{{ busy?'正在处理…':afterSalesCommand[command.action] }}</AppButton><AppButton :disabled="busy" @click="command=null">返回核对</AppButton></div>
      </form>
    </NModal>
    <NModal :show="!!responsibilityCommand" preset="card" :title="responsibilityCommand?.responsibility?'更正责任核定':'登记责任核定'" style="width:min(700px,calc(100vw - 48px))" :mask-closable="!busy" :closable="!busy" @update:show="value=>{if(!value&&!busy)responsibilityCommand=null}">
      <form v-if="responsibilityCommand" class="after-operation" @submit.prevent="executeResponsibility">
        <p>{{ responsibilityCommand.reference }} · v{{ responsibilityCommand.version }}。结合合同、故障和检验资料人工核定；保修期限、收费方案及库存不会自动变化。</p>
        <label>责任结果<WorkspaceSelect v-model="responsibilityOutcome" :options="[{label:'请选择责任结果',value:'',disabled:true},{label:'本公司责任',value:'company'},{label:'客户责任',value:'customer'},{label:'第三方责任',value:'third_party'},{label:'暂无法判定',value:'undetermined'}]" :disabled="busy" required /></label>
        <label>核定依据<AppInput v-model.trim="responsibilityBasis" maxlength="400" required :disabled="busy" /></label>
        <label>登记或更正原因<AppInput v-model.trim="reason" maxlength="200" required :disabled="busy" /></label>
        <p v-if="error" role="alert">{{ error }} 输入已保留；请重新加载证据核对。</p>
        <div class="after-toolbar"><AppButton type="submit" variant="primary" :disabled="disabled||!responsibilityOutcome||!responsibilityBasis.trim()||!reason.trim()">保存核定</AppButton><AppButton :disabled="busy" @click="responsibilityCommand=null">返回核对</AppButton></div>
      </form>
    </NModal>
    <NModal :show="!!laborCommand" preset="card" :title="laborCommand?.entryId?'更正维修工时':'登记实际维修工时'" style="width:min(700px,calc(100vw - 48px))" :mask-closable="!busy" :closable="!busy" @update:show="value=>{if(!value&&!busy)laborCommand=null}">
      <form v-if="laborCommand" class="after-operation" @submit.prevent="executeLabor">
        <p>{{ laborCommand.row.reference }} · 净工时 {{ laborCommand.row.labor_hours }} 小时 · v{{ laborCommand.row.version }}</p>
        <p v-if="laborCommand.entryId">更正原记录 #{{ laborCommand.entryId }} 将追加等量反向记录，保留原记录与证据。</p>
        <label v-else>实际维修小时<AppInput v-model.trim="laborHours" type="number" min="0.01" max="100000" step="0.01" required :disabled="busy" /></label>
        <label>原因<AppInput v-model.trim="reason" maxlength="200" required :disabled="busy" /></label>
        <label>实际依据<AppInput v-model.trim="evidence" maxlength="400" required :disabled="busy" /></label>
        <p>工时仅作作业留痕，不自动形成收费、应付或总账人工成本。</p>
        <p v-if="error" role="alert">{{ error }} 输入已保留；请重新加载最新证据后核对。</p>
        <div class="after-toolbar"><AppButton type="submit" variant="primary" :disabled="disabled||!reason.trim()||!evidence.trim()||(!laborCommand.entryId&&!laborHours.trim())">确认记录</AppButton><AppButton :disabled="busy" @click="laborCommand=null">返回核对</AppButton></div>
      </form>
    </NModal>
  </section>
</template>
<style scoped>
.after-workspace{--after-secondary:#50667d}
:global(:root[data-theme='dark'] .after-workspace){--after-secondary:#9aadc5}
.after-workspace :deep(.after-toolbar),.after-operation .after-toolbar{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.after-workspace :deep(.after-secondary){display:block;margin-top:4px;font-size:12px;color:var(--after-secondary);overflow-wrap:anywhere}
/* 明细按钮聚焦由页面承接滚动，避免隐藏视口的纵向偏移裁掉表头。 */
.after-workspace :deep(.vxe-table--viewport-wrapper){overflow:clip}
.after-workspace :deep(.after-editor form),.after-operation{display:grid;gap:18px}
.after-workspace :deep(.after-wide){grid-column:1/-1}
.after-workspace :deep(.after-material){display:grid;grid-template-columns:minmax(240px,2fr) minmax(150px,1fr) auto;gap:12px;align-items:end;margin-top:12px}
@media(max-width:1000px){.after-workspace :deep(.form-grid){grid-template-columns:repeat(2,minmax(0,1fr))}.after-workspace :deep(.after-material){grid-template-columns:minmax(0,1fr) minmax(120px,1fr)}.after-workspace :deep(.after-material button){justify-self:start}}
</style>
