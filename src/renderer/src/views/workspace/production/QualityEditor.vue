<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
// 物料资料统一展示，候选范围和联动规则仍由当前业务决定。
import WorkspaceMaterialSelect from '../../../components/workspace/WorkspaceMaterialSelect.vue'
import { usePiniaAppStore } from '../../../store/app-store'
const emit=defineEmits<{saved:[];close:[]}>(),store=usePiniaAppStore()
const {qualityForm:form,qualityEdit:edit,qualityOverview:overview,busy,error,connectionLost}=storeToRefs(store)
const source=computed(()=>overview.value?.cases.find(row=>row.id===form.value.completion_id))
const sources=computed(()=>[{label:'选择原质检单',value:0,disabled:true},...(overview.value?.cases??[]).map(row=>({
  label:`完工 #${row.id} · ${row.product_name} · 未占用 ${row.remaining_quantity} ${row.product_unit}`,value:row.id,
  disabled:row.settled || (!edit.value && Number(row.remaining_quantity)<=0)}))])
const materials=computed(()=>[{label:'选择追加材料',value:0,disabled:true},...(overview.value?.materials??[]).filter(row=>row.id!==source.value?.product_material_id).map(row=>({label:`${row.sku} · ${row.name} · ${row.unit}`,value:row.id}))])
const warehouses=computed(()=>(overview.value?.warehouses??[]).map(row=>({label:row.name,value:row.id})))
async function save():Promise<void>{if(await store.saveQualityDisposition())emit('saved')}
</script>
<template>
  <section class="quality-editor" aria-label="编制不合格品处置">
    <div class="quality-toolbar"><h2>{{ edit?'修订':'新建' }}不合格品处置</h2><AppButton :disabled="busy" @click="emit('close')">返回记录</AppButton></div>
    <p>每张处置单选择一种方式，可按原不合格数量分批处理。提交后冻结正文，须由未编制或提交过该单的另一账号审核。</p>
    <form @submit.prevent="save">
      <div class="form-grid">
        <label class="quality-wide">原质检单<WorkspaceSelect v-model="form.completion_id" :options="sources" :disabled="!!edit || busy || connectionLost" required /></label>
        <p v-if="source" class="quality-wide">原工单 #{{ source.work_order_id }} · 合格 {{ source.accepted_quantity }} · 不合格 {{ source.rejected_quantity }} · 已占用 {{ source.reserved_quantity }} {{ source.product_unit }}。{{ source.qc_note }}</p>
        <label>处置依据编号<AppInput v-model.trim="form.reference" maxlength="100" required :disabled="busy" /></label>
        <label>本次处置数量<AppInput v-model="form.quantity" type="number" min="0.001" max="1000000" step="0.001" required :disabled="busy" /></label>
        <label>处置方式<WorkspaceSelect v-model="form.kind" :options="[{label:'报废',value:'scrap'},{label:'返工并重新检验',value:'rework'}]" :disabled="busy" /></label>
        <label v-if="form.kind==='scrap'">报废成本处理<WorkspaceSelect v-model="form.loss_treatment" :options="[{label:'明确选择成本处理',value:'',disabled:true},{label:'由合格品承担',value:'absorb'},{label:'独立报废损失',value:'expense'}]" :disabled="busy" required /></label>
        <label v-else>返工合格品目标仓库<WorkspaceSelect v-model="form.warehouse_id" :options="warehouses" :disabled="busy" required /></label>
        <p class="quality-wide">{{ form.kind==='rework'?'原成本携带至返工工单，加上追加材料、人工及制造费用。原不合格品不进入可用库存。':'由合格品承担须有合格产出；独立损失按已批准数量分摊，再由财务核对科目生成凭证。此处不直接过账。' }}</p>
        <label class="quality-wide">缺陷记录<AppInput v-model.trim="form.defect" maxlength="400" required :disabled="busy" /></label>
        <label class="quality-wide">处置或返工说明<AppInput v-model.trim="form.action_note" maxlength="400" required :disabled="busy" /></label>
      </div>
      <section v-if="form.kind==='rework'" aria-label="返工追加材料">
        <div class="quality-toolbar"><h3>追加材料</h3><AppButton :disabled="busy || form.materials.length>=100" @click="form.materials.push({material_id:0,quantity:'1'})">添加材料</AppButton></div>
        <p v-if="!form.materials.length">无需追加材料时保持为空，返工下达后可登记人工和制造费用。</p>
        <div v-for="(line,index) in form.materials" :key="index" class="quality-material">
          <label>材料 {{ index+1 }}<WorkspaceMaterialSelect :materials="overview?.materials ?? []" v-model="line.material_id" :options="materials" :disabled="busy" required /></label>
          <label>本次返工总需量<AppInput v-model="line.quantity" type="number" min="0.001" max="1000000" step="0.001" required :disabled="busy" /></label>
          <AppButton :disabled="busy" :aria-label="`移除材料 ${index+1}`" @click="form.materials.splice(index,1)">移除</AppButton>
        </div>
      </section>
      <label>{{ edit?'修订原因':'建立原因' }}<AppInput v-model.trim="form.reason" maxlength="200" required :disabled="busy" /></label>
      <p v-if="error" role="alert">{{ error }} 输入已保留；复核原质检数量或重新加载最新版本后重试。</p>
      <AppButton type="submit" variant="primary" :disabled="busy || connectionLost || !source || !form.reason.trim() || (form.kind==='scrap' && !form.loss_treatment)">{{ busy?'正在保存…':'保存处置草稿' }}</AppButton>
    </form>
  </section>
</template>
