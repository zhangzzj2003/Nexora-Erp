<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref,watch} from 'vue'
import {storeToRefs} from 'pinia'
import {RouterLink} from 'vue-router'
import {NCheckbox,NCollapse} from 'naive-ui'
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

const store=usePiniaAppStore()
const {warningOverview:overview,warningDetail:detail,warningLoading:loading,warningError:failure,
  warningEvents:eventPage,warningEventsLoading:eventLoading,warningEventsError:eventFailure,
  warningWarehouseId:warehouse,warningForm:form,warningEditing:editing,busy,user,server,connectionLost,error}=storeToRefs(store)
const query=ref(''),filter=ref<string|null>('attention'),preparing=ref(false)
const disabled=computed(()=>busy.value || loading.value || preparing.value || connectionLost.value)
const mayManage=computed(()=>store.can('inventory_warning.manage') && store.can('inventory.view'))
const rows=computed(()=>(overview.value?.rows??[]).filter(row=>(!filter.value || (filter.value==='attention'
  ? ['low','out_of_stock'].includes(row.status) : row.status===filter.value))
  && [row.warehouse_code,row.warehouse_name,row.sku,row.material_name].join(' ').toLowerCase().includes(query.value.trim().toLowerCase())))
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
function rowRecord(value:Record<string,unknown>):InventoryWarningRow|undefined{return overview.value?.rows.find(row=>row.id===value.id)}
async function open(value:Record<string,unknown>,edit=false):Promise<void>{
  const row=rowRecord(value);if(!row || disabled.value)return
  preparing.value=true
  try{if(edit)await store.editWarningRule(row);else await store.loadWarningDetail(row)}finally{preparing.value=false}
}
function start():void{store.startWarningRule()}
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
onUnmounted(()=>{store.clearWarningDetail()})
const statusOptions=[{value:'attention',label:'缺货或低库存'},...Object.entries(inventoryWarningLabels).map(([value,label])=>({value,label})),{value:null,label:'全部规则'}]
const statusLabel=(value:unknown)=>inventoryWarningLabels[value as InventoryWarningStatus]??'未知状态'
</script>

<template>
  <section class="stack warnings-page">
    <p v-if="!store.can('inventory.view')" role="status">当前账号没有库存查看权限，请联系管理员核对授权。</p>
    <template v-else>
      <p v-if="connectionLost" role="alert">服务端连接已中断，旧库存数量和证据已失效。未保存阈值与修订版本保留；恢复后请核对最新记录。</p>
      <p v-if="failure" role="alert">{{ failure }} 请刷新预警后重试。</p>
      <form v-if="editing && mayManage" class="warning-editor stack" @submit.prevent="store.saveWarningRule()">
        <div class="warning-heading"><h2>{{ form.version ? '修订预警规则' : '配置库存预警' }}</h2><AppButton type="button" :disabled="disabled" @click="editing=false">返回规则</AppButton></div>
        <p v-if="form.version" class="warning-muted">正在修订旧版本 v{{ form.version }}。冲突时保留本次输入，请返回规则读取最新证据后重新修订。</p>
        <div class="warning-form-grid">
          <label>预警仓库<WorkspaceSelect v-model="form.warehouse_id" :options="warehouseOptions" placeholder="选择仓库" :disabled="disabled || form.version>0" /></label>
          <label>预警物料<WorkspaceMaterialSelect :materials="overview?.materials ?? []" v-model="form.material_id" :options="materialOptions" placeholder="选择物料" :disabled="disabled || form.version>0" /></label>
          <label>现存量预警阈值<AppInput v-model="form.threshold" inputmode="decimal" required placeholder="例如 10.000" :disabled="disabled" /></label>
          <label class="warning-toggle"><NCheckbox v-model:checked="form.enabled" :disabled="disabled">启用此仓库与物料的预警</NCheckbox></label>
        </div>
        <p class="warning-muted">阈值按物料单位填写，非负、最多三位小数、不超过一百万。现存量为零或负数时显示缺货；正现存量达到阈值显示正常。</p>
        <p v-if="duplicate" role="alert">此组合已有规则，请返回列表读取最新版本后修订。</p>
        <label>配置或修订原因<AppInput v-model="form.reason" required maxlength="200" :disabled="disabled" /></label>
        <p v-if="error" role="alert">{{ error }}</p>
        <AppButton type="submit" variant="primary" :disabled="invalid">{{ busy ? '正在保存…' : '保存预警规则' }}</AppButton>
      </form>
      <WorkspaceTable v-else title="库存预警" :show-title="false" :columns="columns" :data="rows" :loading="loading" :min-table-width="1000">
        <template #filters>
          <label>查看仓库<WorkspaceSelect v-model="warehouse" :disabled="disabled" :options="[{value:0,label:'全部仓库'},...(overview?.warehouses??[]).map(row=>({value:row.id,label:`${row.code} · ${row.name}`}))]" /></label>
          <label>搜索规则<AppInput v-model="query" placeholder="仓库、物料编码或名称" /></label>
          <label>预警状态<WorkspaceSelect v-model="filter" :options="statusOptions" /></label>
          <AppButton type="button" :disabled="disabled" @click="refresh">刷新预警</AppButton>
          <AppButton v-if="mayManage" type="button" variant="primary" :disabled="disabled || !overview" @click="start">配置预警规则</AppButton>
        </template>
        <template #beforeTable>
          <p v-if="overview" class="warning-summary" role="status">本次范围：缺货 {{ overview.summary.out_of_stock }} 项，低库存 {{ overview.summary.low }} 项，正常 {{ overview.summary.normal }} 项，停用 {{ overview.summary.disabled }} 项；未配置 {{ overview.summary.unconfigured }} 个仓库与物料组合。</p>
        </template>
        <template #cell-warehouse="{row}"><strong>{{ row.warehouse_code }}</strong><span class="warning-muted">{{ row.warehouse_name }}</span></template>
        <template #cell-material="{row}"><strong>{{ row.sku }}</strong><span class="warning-muted">{{ row.material_name }} · {{ row.unit }}</span></template>
        <template #cell-quantity="{row}"><strong>{{ row.quantity }}</strong></template>
        <template #cell-threshold="{row}">{{ row.threshold }}</template>
        <template #cell-shortage="{row}">{{ row.shortage===null ? '不参与预警' : row.shortage }}</template>
        <template #cell-status="{row}">{{ statusLabel(row.status) }} · v{{ row.version }}</template>
        <template #cell-actions="{row}"><div class="warning-actions"><AppButton type="button" :disabled="disabled" @click="open(row)">详情与历史</AppButton><AppButton v-if="mayManage" type="button" :disabled="disabled" @click="open(row,true)">修订规则</AppButton></div></template>
        <template #empty>{{ loading ? '正在读取预警…' : failure ? '读取失败，请刷新重试。' : connectionLost ? '连接中断，旧预警已失效。' : '当前筛选没有匹配规则。未配置的组合不参与预警，请查看全部规则或配置阈值。' }}</template>
      </WorkspaceTable>
      <section v-if="!editing" class="stack warning-evidence" aria-label="服务端库存预警事件">
        <div class="warning-heading"><h3>服务端预警事件</h3><AppButton type="button" :disabled="connectionLost || eventLoading" @click="store.loadWarningEvents()">刷新事件</AppButton></div>
        <p class="warning-muted">服务端约每 60 秒核对一次规则。这里保留首次异常、恢复后再次异常及低库存恶化为缺货的记录；时间和数量是当次核对快照，可能晚于实际库存流水。</p>
        <p v-if="eventFailure" role="alert">{{ eventFailure }} 请重新读取事件。</p>
        <p v-else-if="eventLoading && !eventPage" role="status">正在读取服务端事件…</p>
        <p v-else-if="eventPage && !eventPage.events.length">当前仓库范围尚无服务端预警事件。</p>
        <ol v-if="eventPage?.events.length" class="warning-events">
          <li v-for="item in eventPage.events" :key="item.id">
            <strong>{{ inventoryWarningLabels[item.status] }} · {{ item.warehouse_code }} / {{ item.sku }}</strong>
            <span>核对于 {{ store.localTime(item.observed_at) }} · 现存 {{ item.quantity }} / 阈值 {{ item.threshold }} · 差额 {{ item.shortage }}</span>
            <small>原状态：{{ item.previous_status ? inventoryWarningLabels[item.previous_status] : '首次核对' }} · v{{ item.rule_version }} · {{ item.warehouse_name }} / {{ item.material_name }}（{{ item.unit }}）</small>
          </li>
        </ol>
        <AppButton v-if="eventPage?.next_before_id" type="button" :disabled="eventLoading || connectionLost" @click="store.loadWarningEvents(true)">{{ eventLoading ? '正在加载…' : '加载更早事件' }}</AppButton>
      </section>
      <p class="warning-muted">{{ overview ? `读取时间：${store.localTime(overview.as_of)}。` : '' }}预警按各仓库已确认流水的现存量计算，不含草稿或未来需求，也不等同于 MRP 净需求。未配置与停用规则不表示库存充足。</p>
      <section v-if="detail && !editing" aria-label="库存预警修订证据" class="stack warning-evidence">
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
    </template>
  </section>
</template>

<style scoped>
.warning-heading,.warning-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.warning-heading h2{margin:0}
.warning-form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.warning-toggle{justify-content:center}
.warning-muted{color:#50667d;font-size:13px;overflow-wrap:anywhere}.warning-summary{margin:4px 0 12px;font-size:13px;line-height:1.7}
.warning-facts{display:grid;grid-template-columns:140px minmax(0,1fr);gap:10px 16px;margin:0}.warning-facts dt{color:#50667d;font-size:13px}.warning-facts dd{margin:0;overflow-wrap:anywhere}
.warning-evidence h3{margin:12px 0 0}:deep(td strong),:deep(td .warning-muted){display:block}:deep(td){font-variant-numeric:tabular-nums}
.warning-evidence a{color:var(--workspace-field-accent);text-underline-offset:3px}
.warning-events{display:grid;gap:10px;margin:0;padding-left:24px}.warning-events li{padding:10px 12px;border:1px solid var(--workspace-line,#d9e1ea);border-radius:8px}
.warning-events li strong,.warning-events li span,.warning-events li small{display:block}.warning-events li small{color:#50667d}
:global(:root[data-theme='dark'] .warnings-page .warning-muted),:global(:root[data-theme='dark'] .warnings-page .warning-facts dt){color:#9aadc5}
@media(max-width:600px){.warning-form-grid{grid-template-columns:1fr}.warning-facts{grid-template-columns:1fr;gap:4px}.warning-facts dd{margin-bottom:10px}}
</style>
