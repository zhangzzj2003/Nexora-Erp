<script setup lang="ts">
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { NModal, NPopconfirm, NSwitch, NCollapse } from 'naive-ui'
import AppInput from '../../../components/app/AppInput.vue'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import AppButton from '../../../components/app/AppButton.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { useLocalPagination } from '../../../composables/use-local-pagination'
import { materialCategoryAuditRows } from '../../../utils/material-category-audit'
import type { MaterialCategoryNode, MaterialSpecField, MaterialSpecKind } from '../../../../../shared/material-api'
import './catalog.css'

const store = usePiniaAppStore()
const { materialCategories, busy, connectionLost, materialCategoryDraft: form, materialCategoryEditing: editing,
  materialCategoryEditorOpen: showForm, materialFieldDraft: fieldForm, materialFieldEditorOpen: showField,
  materialCategoryChanges: auditRows } = storeToRefs(store)
const {can, reloadMaterialCategories, saveMaterialCategory, saveMaterialSpecField, removeMaterialCategory, loadMaterialCategoryChanges, localTime} = store
const query = ref(''), status = ref('all'), selectedCode = ref(''), auditOpen = ref(false), auditTitle = ref('')
// 有版本的目录才提供维护；旧服务仍能显示原目录，但不能提交不受校验的新功能。
const nodes = computed(() => materialCategories.value.flatMap(group => [group, ...group.children])
  .filter(node => node.version && node.fields).map(node => node as MaterialCategoryNode))
const filtered = computed(() => nodes.value.filter(node =>
  (status.value === 'all' || node.enabled === (status.value === 'enabled'))
  && `${node.name} ${node.code} ${node.notes}`.toLowerCase().includes(query.value.trim().toLowerCase())))
const filterKey = computed(() => JSON.stringify([query.value, status.value]))
const {rows, total, page, pageSize, changePage} = useLocalPagination(filtered, filterKey)
const selected = computed(() => nodes.value.find(node => node.code === selectedCode.value && node.parent_code))
const fieldCategory = computed(() => nodes.value.find(node => node.code === fieldForm.value.code))
const selectedOptions = computed(() => nodes.value.filter(node => node.parent_code).map(node => ({value:node.code,
  label:`${nodes.value.find(parent => parent.code === node.parent_code)?.name} / ${node.name}${node.enabled ? '' : '（已停用）'}`})))
const parentOptions = computed(() => [{value:'', label:'大类'}, ...nodes.value.filter(node => !node.parent_code)
  .map(node => ({value:node.code,label:node.name,disabled:!node.enabled}))])
const parentValue = computed({get:() => form.value.parent_code ?? '', set:(value: string) => {
  form.value.parent_code = value || null; form.value.code = value ? `${value}-` : ''
}})
const kindOptions: {value: MaterialSpecKind; label: string}[] = [{value:'text',label:'文字'}, {value:'number',label:'数值'}, {value:'enum',label:'选项'}, {value:'boolean',label:'是 / 否'}, {value:'date',label:'日期'}]
const optionsText = computed({get:() => fieldForm.value.options.join('\n'), set:(value: string) => {fieldForm.value.options = value.split('\n').map(entry => entry.trim()).filter(Boolean)}})
const categoryColumns = [{key:'name',title:'类别名称'}, {key:'code',title:'编码前缀'}, {key:'parent',title:'所属大类'},
  {key:'status',title:'状态'}, {key:'material_count',title:'使用物料数'}, {key:'sort_order',title:'排序'}, {key:'actions',title:'操作',width:'270px'}]
const fieldColumns = [{key:'name',title:'字段名称'}, {key:'kind',title:'类型 / 单位'}, {key:'options',title:'常用选项'},
  {key:'required',title:'必填'}, {key:'enabled',title:'状态'}, {key:'sort_order',title:'排序'}, {key:'actions',title:'操作',width:'100px'}]
const auditColumns = [{key:'label',title:'调整项目'}, {key:'before',title:'修改前'}, {key:'after',title:'修改后'}]
const blocked = computed(() => busy.value || connectionLost.value || !can('catalog.manage') || !nodes.value.length)
const modalStyle = {width:'min(820px, calc(100vw - 32px))',maxHeight:'calc(100vh - 64px)',overflowY:'auto' as const}

async function editCategory(code?: string, parent?: string): Promise<void> {
  if (blocked.value || !await reloadMaterialCategories()) return
  const node = nodes.value.find(entry => entry.code === code)
  editing.value = !!node
  form.value = node ? {code:node.code,parent_code:node.parent_code,name:node.name,enabled:node.enabled,
    sort_order:node.sort_order,notes:node.notes,version:node.version,reason:''}
    : {code:parent ? `${parent}-` : '',parent_code:parent ?? null,name:'',enabled:true,sort_order:0,notes:'',reason:''}
  showForm.value = true
}
async function saveCategory(): Promise<void> {
  if (await saveMaterialCategory({...form.value}, editing.value)) {showForm.value = false; form.value.name = ''}
}
async function editField(id?: number): Promise<void> {
  if (!selected.value || blocked.value || !await reloadMaterialCategories()) return
  if (!selected.value) return
  const field = selected.value.fields.find(entry => entry.id === id)
  fieldForm.value = {code:selected.value.code,field_id:field?.id,name:field?.name ?? '',kind:field?.kind ?? 'text',
    unit:field?.unit ?? '',options:field ? [...field.options] : [],allow_custom:field?.allow_custom ?? false,
    required:field?.required ?? false,enabled:field?.enabled ?? true,sort_order:field?.sort_order ?? 0,
    version:selected.value.version,reason:''}
  showField.value = true
}
function changeKind(): void {
  // 仅未使用字段可改类型；切换后清除与新类型不适用的配置。
  if (fieldForm.value.kind !== 'number') fieldForm.value.unit = ''
  if (fieldForm.value.kind !== 'enum') {fieldForm.value.options = []; fieldForm.value.allow_custom = false}
}
const usedField = computed(() => fieldCategory.value?.fields.find(field => field.id === fieldForm.value.field_id)?.used ?? false)
async function saveField(): Promise<void> {
  if (await saveMaterialSpecField({...fieldForm.value,options:[...fieldForm.value.options]})) {showField.value = false; fieldForm.value.name = ''}
}
async function remove(field = false): Promise<void> {
  const draft = field ? fieldForm.value : form.value
  if (!draft.version || !draft.reason) return
  if (await removeMaterialCategory({code:draft.code,version:draft.version,reason:draft.reason}, field ? fieldForm.value.field_id : undefined)) {
    if (field) {showField.value = false; fieldForm.value.name = ''}
    else {showForm.value = false; form.value.name = ''}
  }
}
async function history(node: MaterialCategoryNode): Promise<void> {
  if (await loadMaterialCategoryChanges(node.code)) {auditTitle.value = `${node.name} · 分类与模板变更`; auditOpen.value = true}
}
function fieldKind(field: MaterialSpecField): string {return `${kindOptions.find(option => option.value === field.kind)?.label}${field.unit ? ` / ${field.unit}` : ''}`}
</script>

<template>
  <section class="stack catalog-page">
    <p class="material-hint">大类、子类与规格模板统一维护。名称可以调整，编码前缀固定；停用限制新选择，历史物料和单据继续保留。</p>
    <p v-if="!nodes.length && materialCategories.length" class="material-hint">服务端尚未提供分类与规格模板管理，请升级 ERP 服务。</p>
    <WorkspaceTable :show-title="false" title="物料类别" :columns="categoryColumns" :data="rows" :min-table-width="1050" :pagination="{page,pageSize,total}" @page-change="changePage">
      <template #actions>
        <AppButton v-if="can('catalog.manage')" variant="primary" type="button" :disabled="blocked" @click="editCategory()">新增大类</AppButton>
        <AppButton v-if="can('catalog.manage') && form.name" variant="secondary" type="button" :disabled="blocked" @click="showForm = true">继续类别草稿</AppButton>
        <AppButton v-if="can('catalog.manage') && fieldForm.name" variant="secondary" type="button" :disabled="blocked" @click="showField = true">继续规格草稿</AppButton>
      </template>
      <template #filters>
        <label class="catalog-search">搜索类别<AppInput v-model="query" placeholder="类别名称、前缀或说明" /></label>
        <label class="material-category-filter">状态<WorkspaceSelect v-model="status" :options="[{value:'all',label:'全部'}, {value:'enabled',label:'启用'}, {value:'disabled',label:'停用'}]" /></label>
      </template>
      <template #cell-name="{row}"><strong>{{ row.name }}</strong><p class="material-hint">{{ row.notes }}</p></template>
      <template #cell-parent="{row}">{{ row.parent_code ? nodes.find(node => node.code === row.parent_code)?.name : '大类' }}</template>
      <template #cell-status="{row}">{{ row.enabled ? '启用' : '停用' }}<p v-if="row.parent_code && !nodes.find(node => node.code === row.parent_code)?.enabled" class="material-hint">所属大类已停用</p></template>
      <template #cell-actions="{row}"><div class="catalog-actions">
        <AppButton v-if="can('catalog.manage')" variant="text" type="button" :disabled="blocked" @click="editCategory(row.code)">编辑</AppButton>
        <AppButton v-if="!row.parent_code && can('catalog.manage')" variant="text" type="button" :disabled="blocked || !row.enabled" @click="editCategory(undefined,row.code)">新增子类</AppButton>
        <AppButton v-if="row.parent_code" variant="text" type="button" @click="selectedCode = row.code">规格字段</AppButton>
        <AppButton variant="text" type="button" :disabled="busy || connectionLost" @click="history(row)">变更记录</AppButton>
      </div></template>
      <template #empty>暂无匹配类别。</template>
    </WorkspaceTable>
    <label class="material-category-filter">查看子类规格模板<WorkspaceSelect v-model="selectedCode" :options="selectedOptions" placeholder="选择子类" /></label>
    <WorkspaceTable v-if="selected" :title="`${selected.name} · 规格模板 v${selected.template_version}`" :columns="fieldColumns" :data="selected.fields" :min-table-width="850">
      <template #actions><AppButton v-if="can('catalog.manage')" variant="primary" type="button" :disabled="blocked" @click="editField()">新增规格字段</AppButton></template>
      <template #cell-kind="{row}">{{ fieldKind(row) }}</template>
      <template #cell-options="{row}">{{ row.options.join('、') || '—' }}<p v-if="row.allow_custom" class="material-hint">允许自定义值</p></template>
      <template #cell-required="{row}">{{ row.required ? '是' : '否' }}</template>
      <template #cell-enabled="{row}">{{ row.enabled ? '启用' : '停用' }}</template>
      <template #cell-actions="{row}"><AppButton v-if="can('catalog.manage')" variant="text" type="button" :disabled="blocked" @click="editField(row.id)">编辑</AppButton></template>
      <template #empty>暂无规格字段，可按本类物料的实际参数新增。</template>
    </WorkspaceTable>
    <NModal v-model:show="showForm" preset="card" :style="modalStyle" :mask-closable="!busy" :closable="!busy" :close-on-esc="!busy">
      <form v-if="can('catalog.manage')" class="catalog-editor" @submit.prevent="saveCategory">
        <h3>{{ editing ? '编辑物料类别' : '新增物料类别' }}</h3>
        <fieldset class="material-section" :disabled="blocked"><div class="form-grid">
          <label>层级 / 所属大类<WorkspaceSelect v-model="parentValue" :options="parentOptions" :disabled="editing || blocked" /></label>
          <label>分类短码 *<AppInput v-model.trim="form.code" required maxlength="10" :readonly="editing" :disabled="blocked" placeholder="如 WR 或 WR-HS" /><span class="material-hint">2～4 位大写字母；子类为“大类-短码”。建立后固定。</span></label>
          <label>类别名称 *<AppInput v-model.trim="form.name" required maxlength="80" :disabled="blocked" /></label>
          <label>显示顺序<AppInput v-model.number="form.sort_order" type="number" min="0" max="9999" step="1" required :disabled="blocked" /></label>
          <label>启用<NSwitch v-model:value="form.enabled" :disabled="blocked" aria-label="启用类别" /></label>
          <label>说明<AppInput v-model.trim="form.notes" type="textarea" maxlength="500" :disabled="blocked" /></label>
          <label v-if="editing">修改原因 *<AppInput v-model.trim="form.reason" required maxlength="500" :disabled="blocked" /></label>
        </div></fieldset>
        <p class="material-hint">已使用的类别或仍有子类的大类不能删除，可停用。改名与调整物料分类都不会重新编号。</p>
        <div class="form-actions"><AppButton type="submit" variant="primary" :disabled="blocked">保存类别</AppButton><AppButton type="button" variant="secondary" :disabled="busy" @click="showForm = false">关闭并保留草稿</AppButton>
          <NPopconfirm v-if="editing" @positive-click="remove()"><template #trigger><AppButton type="button" variant="text" :disabled="blocked || !form.reason?.trim()">移除未使用类别</AppButton></template>确认移除？短码仍会保留占用，已使用类别将被拒绝。</NPopconfirm>
        </div>
      </form>
    </NModal>
    <NModal v-model:show="showField" preset="card" :style="modalStyle" :mask-closable="!busy" :closable="!busy" :close-on-esc="!busy">
      <form v-if="can('catalog.manage')" class="catalog-editor" @submit.prevent="saveField">
        <h3>{{ fieldForm.field_id ? '编辑规格字段' : '新增规格字段' }} · {{ fieldCategory?.name }}</h3>
        <fieldset class="material-section" :disabled="blocked"><div class="form-grid">
          <label>字段名称 *<AppInput v-model.trim="fieldForm.name" required maxlength="80" :disabled="blocked" /></label>
          <label>字段类型<WorkspaceSelect v-model="fieldForm.kind" :options="kindOptions" :disabled="blocked || usedField" @change="changeKind" /></label>
          <label v-if="fieldForm.kind === 'number'">单位<AppInput v-model.trim="fieldForm.unit" maxlength="20" :readonly="usedField" :disabled="blocked" placeholder="如 mm、Ω、kg" /></label>
          <label>显示顺序<AppInput v-model.number="fieldForm.sort_order" type="number" min="0" max="9999" step="1" required :disabled="blocked" /></label>
          <label>必填<NSwitch v-model:value="fieldForm.required" :disabled="blocked" aria-label="规格必填" /></label>
          <label>启用<NSwitch v-model:value="fieldForm.enabled" :disabled="blocked" aria-label="启用规格字段" /></label>
          <label v-if="fieldForm.kind === 'enum'">常用选项（每行一项）<AppInput v-model="optionsText" type="textarea" :disabled="blocked" placeholder="每行一个常用选项，最多 50 项" /></label>
          <label v-if="fieldForm.kind === 'enum'">允许自定义值<NSwitch v-model:value="fieldForm.allow_custom" :disabled="blocked" aria-label="允许自定义规格值" /></label>
          <label>修改依据 *<AppInput v-model.trim="fieldForm.reason" required maxlength="500" :disabled="blocked" placeholder="说明新增或调整参数的依据" /></label>
        </div></fieldset>
        <p class="material-hint">已使用字段不能修改类型或单位，需停用后另建字段。停用不会清除历史值；新增必填项不会阻止旧物料仅修改其他资料。</p>
        <div class="form-actions"><AppButton type="submit" variant="primary" :disabled="blocked">保存字段</AppButton><AppButton type="button" variant="secondary" :disabled="busy" @click="showField = false">关闭并保留草稿</AppButton>
          <NPopconfirm v-if="fieldForm.field_id" @positive-click="remove(true)"><template #trigger><AppButton type="button" variant="text" :disabled="blocked || usedField || !fieldForm.reason.trim()">移除未使用字段</AppButton></template>确认移除未使用字段？已使用的字段请停用。</NPopconfirm>
        </div>
      </form>
    </NModal>
    <NModal v-model:show="auditOpen" preset="card" :style="modalStyle" :title="auditTitle">
      <article v-for="entry in auditRows" :key="entry.id" class="catalog-audit-item"><strong>{{ localTime(entry.created_at) }} · {{ entry.changed_by_name }}</strong><span>{{ entry.reason }}</span>
        <small>类别版本 {{ entry.before?.version ?? 0 }} → {{ entry.after.version }}；模板版本 {{ entry.before?.template_version ?? 0 }} → {{ entry.after.template_version }}</small>
        <NCollapse><AppCollapseItem :name="entry.id" title="查看变更前后资料"><WorkspaceTable title="分类与规格调整" :show-title="false" :columns="auditColumns" :data="materialCategoryAuditRows(entry)" :min-table-width="650"><template #empty>本次未调整类别或规格定义。</template></WorkspaceTable></AppCollapseItem></NCollapse>
      </article><p v-if="!auditRows.length" class="material-hint">初始类别由升级收录，尚无人工修改记录。</p>
    </NModal>
  </section>
</template>
