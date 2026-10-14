<script setup lang="ts">
// 来源绑定在真实触发入口，键盘点击与鼠标点击共用同一回程位置。
import { captureDialogOrigin } from '../../../utils/dialog-origin'
import AppModal from '../../../components/app/AppModal.vue'
import {computed,onMounted,onUnmounted,ref,watch} from 'vue'
import {storeToRefs} from 'pinia'
import {RouterLink} from 'vue-router'
import {NCheckbox,NCollapse } from 'naive-ui'
import type {InventoryWarningRow,InventoryWarningStatus} from '../../../../../shared/inventory-warning-api'
import {inventoryWarningLabels,warningThresholdValid} from '../../../../../shared/inventory-warning-api'
import {usePiniaAppStore} from '../../../store/app-store'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
// 物料资料统一展示，候选范围和联动规则仍由当前业务决定。
import WorkspaceMaterialSelect from '../../../components/workspace/WorkspaceMaterialSelect.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
// 概览、筛选、分页与仓库其他列表保持一致；数量始终取完整服务端范围。
import WorkspaceSummaryFilters, {type WorkspaceSummaryFilterOption} from '../../../components/workspace/WorkspaceSummaryFilters.vue'
import WorkspaceSearchFilters from '../../../components/workspace/WorkspaceSearchFilters.vue'
import AppStatusTag from '../../../components/app/AppStatusTag.vue'
import {useLocalPagination} from '../../../composables/use-local-pagination'
import type {WorkspaceSearchFilterField} from '../../../utils/workspace-search-filters'
import {filterWarningRows, warningTone, type WarningFilter} from './warehouse-insights'

const store=usePiniaAppStore()
const {warningOverview:overview,warningDetail:detail,warningLoading:loading,warningError:failure,
  warningEvents:eventPage,warningEventsLoading:eventLoading,warningEventsError:eventFailure,
  warningWarehouseId:warehouse,warningForm:form,warningEditing:editing,busy,user,server,connectionLost,error}=storeToRefs(store)
const query=ref(''),filter=ref<WarningFilter>('attention'),preparing=ref(false),saving=ref(false),detailOpen=ref(false)
const disabled=computed(()=>busy.value || saving.value || loading.value || preparing.value || connectionLost.value)
const mayManage=computed(()=>store.can('inventory_warning.manage') && store.can('inventory.view'))
const filtered=computed(()=>filterWarningRows(overview.value?.rows??[],query.value,filter.value))
const paginationKey=computed(()=>JSON.stringify([warehouse.value,query.value,filter.value]))
const {rows,total,page,pageSize,changePage}=useLocalPagination(filtered,paginationKey)
const summaryOptions=computed<WorkspaceSummaryFilterOption<WarningFilter>[]>(()=>{
  const summary=overview.value?.summary
  return [
    {key:'attention',label:'待关注',count:(summary?.out_of_stock??0)+(summary?.low??0),hint:'缺货与低库存规则',tone:'pending'},
    {key:'out_of_stock',label:'缺货',count:summary?.out_of_stock??0,hint:'现存量为零或负数',tone:'danger'},
    {key:'low',label:'低库存',count:summary?.low??0,hint:'现存量低于预警阈值',tone:'pending'},
    {key:'normal',label:'正常',count:summary?.normal??0,hint:'已启用且达到阈值的规则',tone:'success'},
    {key:'disabled',label:'已停用',count:summary?.disabled??0,hint:'停用规则不参与预警',tone:'neutral'},
  ]
})
const listFilters=computed({get:()=>({warehouse:warehouse.value,status:filter.value}),set:value=>{
  warehouse.value=value.warehouse;filter.value=value.status
}})
const filterFields=computed<WorkspaceSearchFilterField[]>(()=>[
  {kind:'select',key:'warehouse',label:'查看仓库',options:[{value:0,label:'全部仓库'},...(overview.value?.warehouses??[]).map(row=>({value:row.id,label:`${row.code} · ${row.name}`}))]},
  {kind:'select',key:'status',label:'预警状态',options:statusOptions},
])
const resetDisabled=computed(()=>!query.value && !warehouse.value && filter.value==='attention')
function resetFilters():void {query.value='';warehouse.value=0;filter.value='attention'}
function showAllRules():void {query.value='';filter.value='all'}
const columns=[{key:'warehouse',title:'仓库',width:'12%'},{key:'material',title:'物料 / 单位',width:'26%'},{key:'quantity',title:'现存量',width:'10%'},
  {key:'threshold',title:'预警阈值',width:'11%'},{key:'shortage',title:'距阈值差额',width:'12%'},{key:'status',title:'状态 / 版本',width:'12%'},{key:'actions',title:'操作 / 证据',width:'17%'}]
const warehouseOptions=computed(()=>{
  const values=(overview.value?.warehouses??[]).map(row=>({value:row.id,label:`${row.code} · ${row.name}`}))
  if(form.value.warehouse_id && !values.some(row=>row.value===form.value.warehouse_id))values.push({value:form.value.warehouse_id,label:`仓库 #${form.value.warehouse_id}（保留的来源）`})
  return values
})
const materialOptions=computed(()=>{
  const values=(overview.value?.materials??[]).map(row=>({value:row.id,label:`${row.sku} · ${row.name}（${row.unit}）`}))
  if(form.value.material_id && !values.some(row=>row.value===form.value.material_id))values.push({value:form.value.material_id,label:`物料 #${form.value.material_id}（保留的来源）`})
  return values
})
const duplicate=computed(()=>form.value.version===0 && overview.value?.rows.some(row=>row.warehouse_id===form.value.warehouse_id && row.material_id===form.value.material_id))
const invalid=computed(()=>disabled.value || !mayManage.value || !form.value.warehouse_id || !form.value.material_id
  || !warningThresholdValid(form.value.threshold) || !form.value.reason.trim() || duplicate.value)
function rowRecord(value:Pick<InventoryWarningRow,'id'>):InventoryWarningRow|undefined{return overview.value?.rows.find(row=>row.id===value.id)}
// 详情和修订的打开意图独立于服务端结果，等待期间允许取消。
const editorPending = ref(false)
let openRead = 0
async function open(value:Pick<InventoryWarningRow,'id'>,edit=false):Promise<void>{
  const row=rowRecord(value);if(!row || disabled.value)return
  const ticket=++openRead
  preparing.value=true
  if(edit){detailOpen.value=false;editorPending.value=true}else detailOpen.value=true
  try{
    const loaded=edit?await store.editWarningRule(row):await store.loadWarningDetail(row)
    if(ticket!==openRead){if(edit)editing.value=false;return}
    if(!loaded){if(edit)editing.value=false;else detailOpen.value=false}
  }finally{if(ticket===openRead){preparing.value=false;editorPending.value=false}}
}
function start():void{if(!disabled.value && store.startWarningRule())detailOpen.value=false}
// 弹窗只切换可见性，不卸载背景列表；保存及刷新证据期间统一阻止关闭和重复提交。
function updateEditor(show:boolean):void {if(!busy.value && !saving.value){if(!show){openRead++;editorPending.value=false;preparing.value=false}editing.value=show}}
async function saveRule():Promise<void> {
  if(invalid.value)return
  saving.value=true
  try{await store.saveWarningRule()}finally{saving.value=false}
}
function closeDetail():void {openRead++;preparing.value=false;detailOpen.value=false;store.clearWarningDetail()}
watch(detail,value=>{if(!value && !preparing.value)detailOpen.value=false})
function prepareLedger():void {
  if(detail.value)Object.assign(store.ledgerQuery,{warehouse_id:detail.value.row.warehouse_id,
    material_id:detail.value.row.material_id,from_date:'',to_date:'',source_type:null})
}
function refresh():void {void store.loadInventoryWarnings();void store.loadWarningEvents()}
watch(warehouse,refresh)
watch(()=>`${server.value?.id}:${server.value?.fingerprint}:${user.value?.id}:${user.value?.permissions.join('|')}:${connectionLost.value}`,()=>{
  if(!connectionLost.value && store.can('inventory.view'))refresh()
})
onMounted(refresh)
onUnmounted(()=>{openRead++;store.clearWarningDetail()})
const statusOptions=[{value:'attention',label:'缺货或低库存'},...Object.entries(inventoryWarningLabels).map(([value,label])=>({value,label})),{value:'all',label:'全部规则'}]
const statusLabel=(value:unknown)=>inventoryWarningLabels[value as InventoryWarningStatus]??'未知状态'
</script>

<template>
  <section class="stack warnings-page">
    <p v-if="!store.can('inventory.view')" role="status">当前账号没有库存查看权限，请联系管理员核对授权。</p>
    <template v-else>
      <!-- 与工作台标题共用概览区域，读取失败时不把未知数量显示成零。 -->
      <Teleport v-if="overview" defer to="#workspace-page-summary">
        <WorkspaceSummaryFilters v-model="filter" :options="summaryOptions" label="库存预警概览" hint="当前仓库范围 · 点击筛选规则" />
      </Teleport>
      <p v-if="connectionLost" role="alert">服务端连接已中断，旧库存数量和证据已失效。未保存阈值与修订版本保留；恢复后请核对最新记录。</p>
      <p v-if="failure && (editing || overview)" class="warning-notice" role="alert">{{ failure }} 请刷新预警后重试。</p>
      <!-- Naive 弹窗提供焦点锁定；标题和页脚固定，表单仅在正文区滚动。 -->
      <AppModal :busy="busy" origin-key="InventoryWarningsView:form" @invalidated="openRead++; editorPending = false; preparing = false; editing = false" :show="(editing || editorPending) && mayManage" :ready="!editorPending" :load-error="failure" preset="card" role="dialog" aria-modal="true" :title="form.version ? '修订预警规则' : '配置库存预警'"
        class="warning-dialog" :mask-closable="false" :close-on-esc="!busy && !saving" :closable="!busy && !saving"
        :style="{width:'min(760px, calc(100vw - 32px))'}" @update:show="updateEditor">
        <form id="inventory-warning-form" class="warning-editor stack" @submit.prevent="saveRule">
        <p v-if="connectionLost" class="warning-notice" role="alert">服务端连接已中断，本次输入已保留，恢复后请重新核对再保存。</p>
        <p v-if="failure" class="warning-notice" role="alert">{{ failure }}</p>
        <p v-if="form.version" class="warning-muted">正在修订旧版本 v{{ form.version }}。冲突时保留本次输入，请关闭弹窗，读取最新证据后重新修订。</p>
        <div class="warning-form-grid">
          <label>预警仓库<WorkspaceSelect v-model="form.warehouse_id" :options="warehouseOptions" placeholder="选择仓库" :disabled="disabled || form.version>0" /></label>
          <label>预警物料<WorkspaceMaterialSelect :materials="overview?.materials ?? []" v-model="form.material_id" :options="materialOptions" placeholder="选择物料" :disabled="disabled || form.version>0" /></label>
          <label>现存量预警阈值<AppInput v-model="form.threshold" inputmode="decimal" required placeholder="例如 10.000" :disabled="disabled" /></label>
          <label class="warning-toggle"><NCheckbox v-model:checked="form.enabled" :disabled="disabled">启用此仓库与物料的预警</NCheckbox></label>
        </div>
        <p class="warning-muted">阈值按物料单位填写，非负、最多三位小数、不超过一百万。现存量为零或负数时显示缺货；正现存量达到阈值显示正常。</p>
        <p v-if="duplicate" role="alert">此组合已有规则，请关闭弹窗，在列表中读取最新版本后修订。</p>
        <label>配置或修订原因<AppInput v-model="form.reason" required maxlength="200" :disabled="disabled" /></label>
        <p v-if="error" role="alert">{{ error }}</p>
        </form>
        <template #footer>
          <div class="warning-dialog-footer">
            <span class="warning-muted">保存会保留配置或修订原因与版本。</span>
            <div class="warning-actions">
              <AppButton :disabled="busy || saving" @click="updateEditor(false)">取消</AppButton>
              <AppButton type="submit" form="inventory-warning-form" variant="primary" :loading="saving || busy" :disabled="invalid">保存预警规则</AppButton>
            </div>
          </div>
        </template>
      </AppModal>
      <WorkspaceTable title="库存预警" :show-title="false" :columns="columns" :data="rows" :loading="loading" :error="failure"
        :pagination="{page,pageSize,total,disabled:loading}" @page-change="changePage" :min-table-width="1120">
        <template #filters>
          <WorkspaceSearchFilters v-model:query="query" v-model:filters="listFilters" :fields="filterFields"
            search-label="搜索规则" search-placeholder="仓库、物料编码或名称" :disabled="disabled"
            :reset-disabled="resetDisabled" @reset="resetFilters" />
        </template>
        <template #actions>
          <AppButton type="button" :disabled="disabled" :loading="loading" @click="refresh">刷新预警</AppButton>
          <AppButton v-if="mayManage" type="button" variant="primary" :disabled="disabled || !overview" @click.capture="captureDialogOrigin('InventoryWarningsView:form', $event)" @click="start">配置预警规则</AppButton>
        </template>
        <template #beforeTable>
          <div v-if="overview" class="warning-scope" role="status">
            <span>已配置 <strong>{{ overview.summary.configured }}</strong> 项 · 当前显示 <strong>{{ total }}</strong> 项</span>
            <span class="warning-muted">更新于 {{ store.localTime(overview.as_of) }}</span>
          </div>
          <div v-if="overview?.summary.unconfigured" class="warning-notice">
            <AppStatusTag label="待配置" tone="pending" />
            <span>未配置 {{ overview.summary.unconfigured }} 个仓库与物料组合，不参与预警。</span>
          </div>
        </template>
        <template #cell-warehouse="{row}"><strong>{{ row.warehouse_code }}</strong><span class="warning-muted">{{ row.warehouse_name }}</span></template>
        <template #cell-material="{row}"><strong>{{ row.sku }}</strong><span class="warning-muted">{{ row.material_name }} · {{ row.unit }}</span></template>
        <template #cell-quantity="{row}"><strong>{{ row.quantity }}</strong></template>
        <template #cell-threshold="{row}">{{ row.threshold }}</template>
        <template #cell-shortage="{row}">{{ row.shortage===null ? '不参与预警' : row.shortage }}</template>
        <template #cell-status="{row}"><AppStatusTag :label="statusLabel(row.status)" :tone="warningTone(row.status)" /><span class="warning-muted">规则 v{{ row.version }}</span></template>
        <template #cell-actions="{row}"><div class="warning-actions"><AppButton type="button" :disabled="disabled" size="small" variant="text" @click.capture="captureDialogOrigin('InventoryWarningsView:detail', $event)" @click="open(row)">详情与历史</AppButton><AppButton v-if="mayManage" type="button" :disabled="disabled" size="small" variant="text" @click.capture="captureDialogOrigin('InventoryWarningsView:form', $event)" @click="open(row,true)">修订规则</AppButton></div></template>
        <template #errorActions><AppButton :disabled="disabled" @click="refresh">重新读取预警</AppButton></template>
        <template #empty>
          <strong>{{ connectionLost ? '连接中断，旧预警已失效' : !overview?.summary.configured ? '当前范围尚未配置预警规则' : filter==='attention' && !query ? '当前没有缺货或低库存规则' : '没有符合筛选条件的规则' }}</strong>
          <span>未配置与停用规则不表示库存充足，请按实际管理范围核对阈值。</span>
          <div v-if="!connectionLost && overview" class="warning-actions">
            <AppButton v-if="overview.summary.configured" :disabled="disabled" @click="showAllRules">查看全部规则</AppButton>
            <AppButton v-else-if="mayManage" variant="primary" :disabled="disabled" @click.capture="captureDialogOrigin('InventoryWarningsView:form', $event)" @click="start">配置预警规则</AppButton>
          </div>
        </template>
      </WorkspaceTable>
      <section class="warning-evidence warning-event-panel" aria-label="服务端库存预警事件">
        <div class="warning-heading"><div><h3>预警事件</h3><p class="warning-muted">保留首次异常、再次异常与缺货升级记录</p></div><AppButton type="button" :disabled="connectionLost || eventLoading" @click="store.loadWarningEvents()">刷新事件</AppButton></div>
        <!-- 说明复用公共折叠项，保留统一的键盘操作、读屏语义与展开动画。 -->
        <NCollapse class="warning-help"><AppCollapseItem name="event-help" title="事件记录说明"><p>服务端约每 60 秒核对一次规则。这里保留首次异常、恢复后再次异常及低库存恶化为缺货的记录；时间和数量是当次核对快照，可能晚于实际库存流水。</p></AppCollapseItem></NCollapse>
        <p v-if="eventFailure" role="alert">{{ eventFailure }} 请重新读取事件。</p>
        <p v-else-if="eventLoading && !eventPage" role="status">正在读取服务端事件…</p>
        <div v-else-if="eventPage && !eventPage.events.length" class="warning-event-empty"><AppStatusTag label="暂无事件" tone="neutral" /><span>当前仓库范围尚无服务端预警事件。</span></div>
        <ol v-if="eventPage?.events.length" class="warning-events">
          <li v-for="item in eventPage.events" :key="item.id">
            <strong>{{ inventoryWarningLabels[item.status] }} · {{ item.warehouse_code }} / {{ item.sku }}</strong>
            <span>核对于 {{ store.localTime(item.observed_at) }} · 现存 {{ item.quantity }} / 阈值 {{ item.threshold }} · 差额 {{ item.shortage }}</span>
            <small>原状态：{{ item.previous_status ? inventoryWarningLabels[item.previous_status] : '首次核对' }} · v{{ item.rule_version }} · {{ item.warehouse_name }} / {{ item.material_name }}（{{ item.unit }}）</small>
          </li>
        </ol>
        <AppButton v-if="eventPage?.next_before_id" type="button" :disabled="eventLoading || connectionLost" @click="store.loadWarningEvents(true)">{{ eventLoading ? '正在加载…' : '加载更早事件' }}</AppButton>
      </section>
      <p class="warning-footnote">预警按各仓库已确认流水的现存量计算，不含草稿或未来需求，也不等同于 MRP 净需求。未配置与停用规则不表示库存充足。</p>
      <AppModal :busy="busy" origin-key="InventoryWarningsView:detail" @invalidated="closeDetail()" :show="detailOpen && !editing" :ready="!preparing && !!detail" :load-error="failure" preset="card" role="dialog" aria-modal="true" title="预警规则详情与历史"
        class="warning-dialog" :style="{width:'min(820px, calc(100vw - 32px))'}" @update:show="show=>{if(!show)closeDetail()}">
        <section v-if="detail" aria-label="库存预警修订证据" class="stack warning-evidence">
        <h3>{{ detail.row.warehouse_code }} · {{ detail.row.sku }} · v{{ detail.row.version }}</h3>
        <dl class="warning-facts"><dt>仓库与物料</dt><dd>{{ detail.row.warehouse_name }} · {{ detail.row.material_name }} · {{ detail.row.unit }}</dd><dt>本次读取结果</dt><dd>现存 {{ detail.row.quantity }} / 阈值 {{ detail.row.threshold }} · {{ inventoryWarningLabels[detail.row.status] }}</dd></dl>
        <RouterLink to="/workspace/inventory-ledger" @click="prepareLedger">核对本仓库与物料的库存流水</RouterLink>
        <h3>配置与修订历史</h3>
        <NCollapse>
          <AppCollapseItem v-for="change in detail.changes" :key="change.id" :name="change.id" :title="`${change.before ? '修订规则' : '建立规则'} · ${change.changed_by_name} · ${store.localTime(change.created_at)}`">
            <p>原因：{{ change.reason }}</p>
            <p class="warning-muted">修订时来源：{{ change.after.warehouse_code }} · {{ change.after.warehouse_name }} / {{ change.after.sku }} · {{ change.after.material_name }}（{{ change.after.unit }}）</p>
            <dl class="warning-facts"><dt>阈值</dt><dd>{{ change.before?.threshold ?? '未配置' }} → {{ change.after.threshold }}</dd><dt>启停</dt><dd>{{ change.before ? (change.before.enabled ? '启用' : '停用') : '未配置' }} → {{ change.after.enabled ? '启用' : '停用' }}</dd><dt>版本</dt><dd>{{ change.before?.version ?? '无' }} → {{ change.after.version }}</dd></dl>
          </AppCollapseItem>
        </NCollapse>
        </section>
        <template #footer><div class="warning-dialog-footer warning-dialog-footer--end"><AppButton @click="closeDetail">关闭</AppButton></div></template>
      </AppModal>
    </template>
  </section>
</template>

<style scoped>
/* 弹窗页脚独立于正文滚动，取消和保存始终可见；窄窗口允许操作区换行。 */
.warning-dialog-footer{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;padding-top:16px;border-top:1px solid var(--workspace-field-border)}
.warning-dialog-footer--end{justify-content:flex-end}.warning-editor label{display:grid;gap:8px}.warning-editor p{margin:0;line-height:1.7}
/* 次级记录收进独立面板，说明按需展开，主列表优先占据首屏。 */
.warnings-page{gap:20px}
.warning-scope,.warning-notice{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin:0 0 14px;font-size:13px}
.warning-notice{justify-content:flex-start;padding:12px 14px;border-radius:10px;background:var(--workspace-field-disabled);line-height:1.6}
.warning-event-panel{padding:22px 24px;border:1px solid var(--workspace-field-border);border-radius:16px;background:var(--workspace-field-background)}
.warning-event-panel .warning-heading{justify-content:space-between}.warning-event-panel .warning-heading h3{margin:0}.warning-heading p{margin:6px 0 0}
.warning-help{margin:14px 0;color:var(--workspace-field-muted);font-size:13px;line-height:1.7}.warning-help p{margin:8px 0}
.warning-event-empty{display:flex;gap:12px;align-items:center;padding:18px 0 2px;font-size:13px;color:var(--workspace-field-muted);flex-wrap:wrap}
.warning-footnote{margin:0;color:var(--workspace-field-muted);font-size:12px;line-height:1.7}

.warning-heading,.warning-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.warning-heading h2{margin:0}
.warning-form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.warning-toggle{justify-content:center}
.warning-muted{color:var(--workspace-field-muted);font-size:13px;overflow-wrap:anywhere}
.warning-facts{display:grid;grid-template-columns:140px minmax(0,1fr);gap:10px 16px;margin:0}.warning-facts dt{color:var(--workspace-field-muted);font-size:13px}.warning-facts dd{margin:0;overflow-wrap:anywhere}
.warning-evidence h3{margin:12px 0 0}:deep(td strong),:deep(td .warning-muted){display:block}:deep(td){font-variant-numeric:tabular-nums}
.warning-evidence a{color:var(--workspace-field-accent);text-underline-offset:3px}
.warning-events{display:grid;gap:10px;margin:0;padding-left:24px}.warning-events li{padding:10px 12px;border:1px solid var(--workspace-line,#d9e1ea);border-radius:8px}
.warning-events li strong,.warning-events li span,.warning-events li small{display:block}.warning-events li small{color:var(--workspace-field-muted)}
:global(:root[data-theme='dark'] .warnings-page .warning-muted),:global(:root[data-theme='dark'] .warnings-page .warning-facts dt){color:#9aadc5}
@media(max-width:600px){.warning-form-grid{grid-template-columns:1fr}.warning-facts{grid-template-columns:1fr;gap:4px}.warning-facts dd{margin-bottom:10px}}
</style>
