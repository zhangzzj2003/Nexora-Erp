<script setup lang="ts">
import { computed } from 'vue'
import AppInput from '../../../components/app/AppInput.vue'
import AppButton from '../../../components/app/AppButton.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import type { MaterialCategory } from '../../../../../shared/material-api'
import type { MaterialDraft } from './material-form'

// 编辑器只维护表单交互，保存、权限与刷新仍由页面和 Pinia 处理。
const props = defineProps<{
  form: MaterialDraft; categories: MaterialCategory[]; editing: boolean; busy: boolean; disconnected: boolean
}>()
const emit = defineEmits<{ save: []; cancel: [] }>()
const groups = computed(() => props.categories.map(group => ({ value: group.code, label: group.name })))
const children = computed(() => [
  ...(props.editing ? [{ value: '', label: '未分类（保留旧资料）' }] : []),
  ...(props.categories.find(group => group.code === props.form.group_code)?.children ?? [])
    .map(child => ({ value: child.code, label: child.name }))
])
const electronics = computed(() => props.form.group_code === 'EL')
function changeGroup(): void {
  // 切换大类必须重新选择子类；已填参数仍保留，避免误操作丢失草稿。
  props.form.category_code = ''
}
function submit(): void {
  // 空子类仅允许旧档案继续保存；新增必须有类别才能分配前缀。
  if ((!props.editing && !props.form.category_code) || props.busy || props.disconnected) return
  emit('save')
}
</script>

<template>
  <form class="catalog-editor material-editor" @submit.prevent="submit">
    <h3>{{ editing ? '编辑物料' : '新增物料' }}</h3>
    <p class="material-hint">按规格建立物料档案，同一物料可绑定多家供应商。带 * 的项目必填。</p>
    <fieldset :disabled="busy || disconnected" class="material-section">
      <legend>基本资料</legend>
      <div class="form-grid">
        <label>物料大类 *<WorkspaceSelect v-model="form.group_code" :options="groups" required aria-label="物料大类" :disabled="busy || disconnected" @change="changeGroup" /></label>
        <label>物料子类 {{ editing ? '' : '*' }}<WorkspaceSelect v-model="form.category_code" :options="children" :required="!editing" placeholder="请选择物料子类" aria-label="物料子类" :disabled="busy || disconnected" /></label>
        <label class="material-wide">物料编码<AppInput :model-value="editing ? form.sku : form.category_code ? `${form.category_code}-######` : '选择子类后，保存时自动生成'" readonly aria-label="物料编码" />
          <span class="material-hint">{{ editing ? '编码固定；调整分类后保留原编码，保证历史单据追溯。' : '各子类独立使用六位流水号，由服务端统一分配，删除后不复用。' }}</span>
        </label>
        <label>物料名称 *<AppInput v-model.trim="form.name" required maxlength="120" placeholder="如：贴片电阻" /></label>
        <label>单位 *<AppInput v-model.trim="form.unit" required maxlength="20" placeholder="如：件、个、米、千克" /></label>
        <label>规格型号<AppInput v-model.trim="form.specification" maxlength="200" placeholder="如：10kΩ ±1% 1/10W；尺寸、材质等" /></label>
        <label>封装 / 外形<AppInput v-model.trim="form.package" maxlength="80" placeholder="如：0603、SOP-8、插件" /></label>
        <label>品牌 / 制造商<AppInput v-model.trim="form.brand" maxlength="120" placeholder="如：国巨、村田、TI" /></label>
        <label>制造商料号<AppInput v-model.trim="form.manufacturer_part_number" maxlength="120" placeholder="制造商的具体型号或订货料号" /></label>
      </div>
    </fieldset>
    <fieldset v-if="electronics" :disabled="busy || disconnected" class="material-section">
      <legend>电子参数（选填）</legend>
      <div class="form-grid">
        <label>标称值 / 关键参数<AppInput v-model.trim="form.electrical_value" maxlength="80" placeholder="如：10kΩ、100nF、主控芯片" /></label>
        <label>精度 / 容差<AppInput v-model.trim="form.tolerance" maxlength="80" placeholder="如：±1%、±5%" /></label>
        <label>额定电压<AppInput v-model.trim="form.rated_voltage" maxlength="80" placeholder="如：50V" /></label>
        <label>额定功率<AppInput v-model.trim="form.rated_power" maxlength="80" placeholder="如：0.1W" /></label>
        <label>工作温度<AppInput v-model.trim="form.temperature_range" maxlength="80" placeholder="如：-40℃～85℃" /></label>
      </div>
    </fieldset>
    <fieldset :disabled="busy || disconnected" class="material-section">
      <legend>其他资料</legend>
      <div class="form-grid">
        <label class="material-wide">环保 / 合规要求<AppInput v-model.trim="form.compliance" maxlength="120" placeholder="如：RoHS、无铅；仅记录已确认要求" /></label>
        <label class="material-wide">备注<AppInput v-model.trim="form.notes" maxlength="1000" placeholder="如：材质、颜色、表面处理、包装及存储要求" /></label>
        <label v-if="editing" class="material-wide">修改原因 *<AppInput v-model.trim="form.reason" required maxlength="500" placeholder="说明本次补充或调整的原因" /></label>
      </div>
    </fieldset>
    <div class="form-actions">
      <AppButton :disabled="busy || disconnected || (!editing && !form.category_code)" variant="primary" type="submit">{{ busy ? '保存中…' : '保存' }}</AppButton>
      <AppButton type="button" :disabled="busy" @click="emit('cancel')" variant="secondary">取消</AppButton>
    </div>
  </form>
</template>
