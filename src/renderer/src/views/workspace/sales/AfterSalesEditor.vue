<script setup lang="ts">
// 来源选择显示正式出库编号，旧响应仍由公共格式化函数兼容。
import {relatedDocumentLabel} from '../../../../../shared/document-numbering'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import {documentRows} from '../../../utils/document-rows'
import {computed,watch} from 'vue'
import {storeToRefs} from 'pinia'
import {usePiniaAppStore} from '../../../store/app-store'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
// 物料资料统一展示，候选范围和联动规则仍由当前业务决定。
import WorkspaceMaterialSelect from '../../../components/workspace/WorkspaceMaterialSelect.vue'
// 弹窗已有固定标题和关闭区，内嵌使用时仍保留原页头。
withDefaults(defineProps<{dialog?:boolean}>(),{dialog:false})
const emit=defineEmits<{close:[];saved:[]}>()
const store=usePiniaAppStore()
const {afterSalesForm:form,afterSalesEdit:edit,afterSalesOverview:overview,busy,error,connectionLost}=storeToRefs(store)
// 耗材表继续直接使用售后草稿行，数量与仓库约束不随布局改变。
const partRows=computed(()=>documentRows(form.value.parts))
const partColumns=[{key:'material',title:'耗材 / 资料',width:'400'},{key:'quantity',title:'整单使用数量',width:'180'},{key:'actions',title:'操作',width:'100'}]
const original=computed(()=>overview.value?.sources.find(row=>row.shipment_line_id===form.value.shipment_line_id))
const sources=computed(()=>(overview.value?.sources??[]).map(row=>({label:`出库 ${relatedDocumentLabel(row,'shipment')} · ${row.customer_name} · ${row.sku} · 剩余 ${row.remaining_quantity} ${row.unit}`,value:row.shipment_line_id})))
const materials=computed(()=>(overview.value?.materials??[]).map(row=>({label:`${row.sku} · ${row.name}（${row.unit}）`,value:row.id})))
const warehouses=computed(()=>(overview.value?.warehouses??[]).map(row=>({label:row.name,value:row.id})))
const warrantyDays=computed({get:()=>form.value.warranty_days==null?'':String(form.value.warranty_days),
  set:(value:string)=>{form.value.warranty_days=value===''?null:Number(value)}})
watch(()=>form.value.kind,(kind,previous)=>{
  if(kind==='repair' && previous!==kind)form.value.charge_mode=''
  if(kind==='exchange'){form.value.replacement_quantity??=form.value.quantity;form.value.replacement_unit_price??='';form.value.replacement_material_id??=original.value?.material_id??null}
})
watch(()=>form.value.shipment_line_id,(lineId,previous)=>{
  if(edit.value || lineId===previous)return
  const selected=overview.value?.sources.find(row=>row.shipment_line_id===lineId)
  form.value.warranty_days=selected?.warranty_days??null
  form.value.warranty_basis=selected?.warranty_basis??''
})
async function save():Promise<void>{if(await store.saveAfterSalesCase())emit('saved')}
</script>
<template>
  <section class="after-editor" :class="{'sales-editor-shell':dialog}" aria-label="编制售后申请">
    <div v-if="!dialog" class="after-toolbar"><h3>{{ edit?`修订售后 #${edit.id} · v${edit.version}`:'编制售后申请' }}</h3><AppButton :disabled="busy" @click="emit('close')">返回记录</AppButton></div>
    <form @submit.prevent="save">
      <div class="sales-editor-body">
      <p>关联原出库数量，填写客户诉求、明确办理方案与客户同意依据；提交后按角色当前步骤权限办理审批。</p>
      <div class="form-grid sales-editor-basic">
        <label class="after-wide">原出库明细<WorkspaceSelect v-model="form.shipment_line_id" :options="sources" :disabled="!!edit || busy || connectionLost" required /></label>
        <p v-if="original" class="after-wide">{{ original.customer_name }} · {{ original.sku }} · 原出库 {{ original.quantity }} {{ original.unit }}，可办理 {{ original.remaining_quantity }} {{ original.unit }}。</p>
        <label>售后依据编号<AppInput v-model.trim="form.reference" maxlength="100" required :disabled="busy" /></label>
        <label>本次办理数量<AppInput v-model="form.quantity" type="number" min="0.001" max="1000000" step="0.001" required :disabled="busy" /></label>
        <label>处理方式<WorkspaceSelect v-model="form.kind" :options="[{label:'退货',value:'return'},{label:'换货',value:'exchange'},{label:'维修',value:'repair'}]" :disabled="busy" /></label>
        <label v-if="form.kind!=='repair'">退回公司库存的仓库<WorkspaceSelect v-model="form.warehouse_id" :options="warehouses" required :disabled="busy" /></label>
        <label class="after-wide">客户诉求与故障<AppInput v-model.trim="form.complaint" maxlength="400" required :disabled="busy" /></label>
        <label>约定保修天数（可留空）<AppInput v-model="warrantyDays" type="number" min="1" max="36500" step="1" :disabled="busy || original?.warranty_days != null" /></label>
        <label class="after-wide">保修合同或承诺依据<AppInput v-model.trim="form.warranty_basis" maxlength="400" :required="form.warranty_days!==null" :disabled="busy || original?.warranty_days != null" /></label>
        <p v-if="original?.warranty_days != null" class="after-wide">保修条款已从原销售订单带入并固定；如条款有误，须核对原合同及订单证据。</p>
        <p class="after-wide">保修期限从原出库的 UTC 日期起算，建单日期作为申请日；没有可靠条款时两项都留空，显示“未确认”。期限判断仅供独立审核参考，不自动决定责任或收费。</p>
        <label class="after-wide">办理方案<AppInput v-model.trim="form.solution" maxlength="400" required :disabled="busy" /></label>
        <template v-if="form.kind==='exchange'">
          <label>换货销售物料<WorkspaceMaterialSelect use="can_sell" :materials="overview?.materials ?? []" v-model="form.replacement_material_id" :options="materials" required :disabled="busy" /></label>
          <label>换货交付数量<AppInput v-model="form.replacement_quantity" type="number" min="0.001" step="0.001" max="1000000" required :disabled="busy" /></label>
          <label>换货销售单价（元）<AppInput v-model="form.replacement_unit_price" type="number" min="0" step="0.0001" max="1000000000" required :disabled="busy" /></label>
          <p class="after-wide">原退货沿用原销售价格；换货建立独立销售订单，以上价格须明确填写。两个订单分别核对，不自动抵销价差。</p>
        </template>
        <template v-if="form.kind==='repair'">
          <label>维修收费方式<WorkspaceSelect v-model="form.charge_mode" :options="[{label:'明确选择免费或收费',value:'',disabled:true},{label:'免费维修',value:'free'},{label:'收费维修',value:'charge'}]" required :disabled="busy" /></label>
          <label v-if="form.charge_mode==='charge'">整单维修服务费（元）<AppInput v-model="form.fee_amount" type="number" min="0.01" step="0.01" max="1000000000" required :disabled="busy" /></label>
          <p class="after-wide">客户维修品独立登记保管，不计入公司可售库存。服务费是整单金额，检验合格并实际交还客户后才进入原订单应收；责任及收费方案须由审核人结合合同和客户同意依据核定。</p>
        </template>
        <label class="after-wide">客户同意方案与价格的依据<AppInput v-model.trim="form.customer_acceptance" maxlength="400" required :disabled="busy" /></label>
      </div>
      <section v-if="form.kind==='repair'" aria-label="维修公司耗材">
        <label v-if="form.parts.length">公司耗材出库仓<WorkspaceSelect v-model="form.warehouse_id" :options="warehouses" required :disabled="busy" /></label>
        <WorkspaceTable title="公司维修耗材" actions-placement="heading" :data="partRows" :columns="partColumns" :min-table-width="680" empty-text="不使用公司材料时保持为空，客户物品本身不作为公司耗材出库。">
          <template #actions><AppButton :disabled="busy || form.parts.length>=100" @click="form.parts.push({material_id:0,quantity:'1'})">添加耗材</AppButton></template>
          <template #cell-material="{row:{line,index}}"><WorkspaceMaterialSelect :materials="overview?.materials ?? []" v-model="line.material_id" :options="materials" :aria-label="`第 ${index+1} 行耗材`" required :disabled="busy" /></template>
          <template #cell-quantity="{row:{line,index}}"><AppInput v-model="line.quantity" :aria-label="`第 ${index+1} 行整单使用数量`" type="number" min="0.001" step="0.001" max="1000000" required :disabled="busy" /></template>
          <template #cell-actions="{row:{index}}"><AppButton size="small" :disabled="busy" :aria-label="`移除耗材 ${index+1}`" @click="form.parts.splice(index,1)">移除</AppButton></template>
        </WorkspaceTable>
      </section>
      <label>{{ edit?'修订原因':'建立原因' }}<AppInput v-model.trim="form.reason" maxlength="200" required :disabled="busy" /></label>
      <p v-if="error" role="alert">{{ error }} 输入已保留；复核原出库数量或刷新最新版本后重试。</p>
      </div>
      <div class="after-editor-actions sales-editor-footer"><AppButton v-if="dialog" type="button" :disabled="busy" @click="emit('close')">取消</AppButton>
      <AppButton type="submit" variant="primary" :disabled="busy || connectionLost || !original || (form.kind==='repair' && !['free','charge'].includes(form.charge_mode))">{{ busy?'正在保存…':'保存售后草稿' }}</AppButton></div>
    </form>
  </section>
</template>

<style scoped>
/* 底部动作与销售单据一致靠右，窄窗自动换行。 */
.after-editor-actions {display:flex;flex-wrap:wrap;justify-content:flex-end;gap:10px}
</style>
