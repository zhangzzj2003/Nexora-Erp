<script setup lang="ts">
import { computed, watch } from 'vue'
import { NCollapse } from 'naive-ui'
import AppInput from '../../../components/app/AppInput.vue'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import AppButton from '../../../components/app/AppButton.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import { prepareMaterialSpecs } from '../../../utils/material-form.ts'
import type { MaterialDraft } from '../../../utils/material-form'
import type { MaterialCategory, MaterialSpecValueInput, MaterialSpecStatus, MaterialSpecField } from '../../../../../shared/material-api'

const props = defineProps<{form: MaterialDraft; categories: MaterialCategory[]; disabled: boolean}>()
// 模板只在首次选择时复制，目录后来更新时提示重读，避免悄悄解释已经输入的值。
watch(() => [props.form, props.form.category_code, props.categories], () => prepareMaterialSpecs(props.form, props.categories), {immediate: true})
const template = computed(() => props.form.spec_templates[props.form.category_code])
const entries = computed(() => props.form.spec_drafts[props.form.category_code] ?? [])
const current = computed(() => props.categories.flatMap(group => group.children).find(child => child.code === props.form.category_code))
const archived = computed(() => props.form.historical_specs.filter(entry => entry.historical || entry.category_code !== props.form.category_code))
const statusOptions = [{value:'filled',label:'已填写'}, {value:'unknown',label:'未知'}, {value:'not_applicable',label:'不适用'}, {value:'pending',label:'待确认'}] satisfies {value: MaterialSpecStatus; label: string}[]
function setStatus(entry: MaterialSpecValueInput, status: MaterialSpecStatus): void {
  entry.status = status
  if (status !== 'filled') entry.value = null
}
function setText(entry: MaterialSpecValueInput, value: string): void {entry.value = value}
function enumOptions(field: MaterialSpecField, entry: MaterialSpecValueInput) {
  // 控件内部使用独立选项键，避免用户填写的规格值恰好等于“自定义”标记。
  return [...field.options.map((value, index) => ({value:`preset:${index}`, label:value})),
    ...(field.allow_custom || (!!entry.value && !field.options.includes(String(entry.value))) ? [{value:'custom', label:'自定义 / 保留原值'}] : [])]
}
function enumChoice(field: MaterialSpecField, entry: MaterialSpecValueInput): string {
  const index = field.options.indexOf(String(entry.value ?? ''))
  return props.form.spec_custom[field.id] ? 'custom' : index >= 0 ? `preset:${index}` : ''
}
function selectEnum(field: MaterialSpecField, entry: MaterialSpecValueInput, value: string): void {
  props.form.spec_custom[field.id] = value === 'custom'
  entry.value = value === 'custom' ? '' : field.options[Number(value.slice('preset:'.length))] ?? ''
}
function extra(): void {
  if (!props.disabled && props.form.extra_attributes.length < 20) props.form.extra_attributes.push({name:'', value:'', unit:''})
}
</script>

<template>
  <fieldset :disabled="disabled" class="material-section">
    <legend>分类规格字段</legend>
    <p class="material-hint">按所选子类填写；数值和单位分别保存。未知、不适用和待确认不会当成零。旧档案仅改其他资料时，可保留未补齐的规格。</p>
    <p v-if="template && template.version !== current?.template_version" class="material-hint">规格模板已更新。当前输入已保留；请先复制或核对输入，再重新打开最新物料。主动保存规格会提示版本冲突。</p>
    <p v-if="!template?.fields.length" class="material-hint">当前子类没有启用的规格字段，可到“基础资料 → 物料分类与规格”维护。</p>
    <div v-for="(field, index) in template?.fields ?? []" :key="field.id" class="specification-row">
      <template v-if="entries[index]">
        <label>{{ field.name }} {{ field.required ? '*' : '' }}<WorkspaceSelect :model-value="entries[index]!.status" :options="statusOptions" :aria-label="`${field.name}填写状态`" :disabled="disabled" @update:model-value="value => setStatus(entries[index]!, value)" /></label>
        <label v-if="entries[index]!.status === 'filled'">{{ field.unit ? `数值（${field.unit}）` : '规格值' }}
          <WorkspaceSelect v-if="field.kind === 'boolean'" :model-value="entries[index]!.value === true ? 'yes' : entries[index]!.value === false ? 'no' : ''" :options="[{value:'yes',label:'是'}, {value:'no',label:'否'}]" required :aria-label="field.name" :disabled="disabled" @update:model-value="value => entries[index]!.value = value === 'yes'" />
          <template v-else-if="field.kind === 'enum'">
            <WorkspaceSelect :model-value="enumChoice(field, entries[index]!)" :options="enumOptions(field, entries[index]!)" :aria-label="field.name" :disabled="disabled" @update:model-value="value => selectEnum(field, entries[index]!, value)" />
            <AppInput v-if="form.spec_custom[field.id]" :model-value="String(entries[index]!.value ?? '')" required maxlength="120" placeholder="输入自定义规格" :disabled="disabled" @update:model-value="value => setText(entries[index]!, value)" />
          </template>
          <AppInput v-else :model-value="String(entries[index]!.value ?? '')" required maxlength="500" :inputmode="field.kind === 'number' ? 'decimal' : undefined" :placeholder="field.kind === 'date' ? 'YYYY-MM-DD' : field.kind === 'number' ? `请输入数值，单位 ${field.unit || '无'}` : '填写规格值'" :disabled="disabled" @update:model-value="value => setText(entries[index]!, value)" />
        </label>
        <label>确认依据 / 来源<AppInput v-model="entries[index]!.source" maxlength="500" placeholder="如：规格书版本、图纸号、供应商确认" :disabled="disabled" /></label>
      </template>
    </div>
    <NCollapse v-if="archived.length"><AppCollapseItem name="historical" :title="`保留的历史规格（${archived.length} 项）`">
      <p v-for="entry in archived" :key="entry.field_id">{{ entry.category_code }} · {{ entry.name }}：{{ entry.status === 'filled' ? `${typeof entry.value === 'boolean' ? entry.value ? '是' : '否' : entry.value}${entry.unit}` : statusOptions.find(option => option.value === entry.status)?.label }} {{ entry.source ? `｜${entry.source}` : '' }}</p>
    </AppCollapseItem></NCollapse>
  </fieldset>
  <fieldset :disabled="disabled" class="material-section">
    <legend>非标准扩展属性</legend>
    <p class="material-hint">特殊参数可单独记录，最多 20 项；不会自动变成其他物料的模板字段。</p>
    <div v-for="(entry, index) in form.extra_attributes" :key="index" class="specification-row">
      <label>属性名称<AppInput v-model.trim="entry.name" required maxlength="80" :disabled="disabled" /></label>
      <label>属性值<AppInput v-model.trim="entry.value" required maxlength="500" :disabled="disabled" /></label>
      <label>单位（可选）<AppInput v-model.trim="entry.unit" maxlength="20" :disabled="disabled" /></label>
      <AppButton type="button" variant="text" :disabled="disabled" @click="form.extra_attributes.splice(index, 1)">移除属性</AppButton>
    </div>
    <AppButton type="button" variant="secondary" :disabled="disabled || form.extra_attributes.length >= 20" @click="extra">添加扩展属性</AppButton>
  </fieldset>
</template>

<style scoped>
/* 字段、值和来源成行对照；窄屏按自然顺序排列，保留完整中文标签。 */
.specification-row {display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin:16px 0; align-items:start;}
.specification-row label {min-width:0; display:grid; gap:8px;}
@media(max-width:700px) {.specification-row {grid-template-columns:minmax(0,1fr);}}
</style>
