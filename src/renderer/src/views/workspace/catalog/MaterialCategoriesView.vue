<script setup lang="ts">
// 来源绑定在真实触发入口，键盘点击与鼠标点击共用同一回程位置。
import { captureDialogOrigin } from '../../../utils/dialog-origin'
import AppModal from '../../../components/app/AppModal.vue'
import { computed, ref, watch, onUnmounted } from 'vue'
import { storeToRefs } from 'pinia'
import {  NPopconfirm, NSwitch, NCollapse } from 'naive-ui'
import AppInput from '../../../components/app/AppInput.vue'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import AppButton from '../../../components/app/AppButton.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { materialCategoryAuditRows } from '../../../utils/material-category-audit'
import type { MaterialCategoryNode, MaterialSpecField, MaterialSpecKind } from '../../../../../shared/material-api'
import { categorySupportsManagement, materialCategoryTreeRows, type MaterialCategoryStatus } from './material-category-tree'
import './catalog.css'

const store = usePiniaAppStore()
const { materialCategories, busy, connectionLost, materialCategoryDraft: form, materialCategoryEditing: editing,
  materialCategoryEditorOpen: showForm, materialFieldDraft: fieldForm, materialFieldEditorOpen: showField,
  materialCategoryChanges: auditRows } = storeToRefs(store)
const {can, reloadMaterialCategories, saveMaterialCategory, saveMaterialSpecField, removeMaterialCategory, loadMaterialCategoryChanges, localTime} = store
const query = ref(''), status = ref<MaterialCategoryStatus>('all'), selectedCode = ref(''), auditOpen = ref(false), auditTitle = ref('')
const collapsedGroups = ref(new Set<string>())
// 有版本的目录才提供维护；旧服务仍能显示原目录，但不能提交不受校验的新功能。
const nodes = computed(() => materialCategories.value.flatMap(group => [group, ...group.children])
  .filter(categorySupportsManagement))
// 不按行分页，大类与子类始终在同一段目录内；筛选展开不改写手动收起记录。
const filtering = computed(() => !!query.value.trim() || status.value !== 'all')
const rows = computed(() => materialCategoryTreeRows(materialCategories.value, query.value, status.value, collapsedGroups.value))
const selected = computed(() => nodes.value.find(node => node.code === selectedCode.value && node.parent_code))
const fieldCategory = computed(() => nodes.value.find(node => node.code === fieldForm.value.code))
const categoryPath = (node: MaterialCategoryNode): string => node.parent_code
  ? `${materialCategories.value.find(parent => parent.code === node.parent_code)?.name ?? node.parent_code} / ${node.name}` : node.name
const selectedPath = computed(() => selected.value ? categoryPath(selected.value) : '')
const parentOptions = computed(() => [{value:'', label:'大类'}, ...nodes.value.filter(node => !node.parent_code)
  .map(node => ({value:node.code,label:node.name,disabled:!node.enabled}))])
const parentValue = computed({get:() => form.value.parent_code ?? '', set:(value: string) => {
  form.value.parent_code = value || null; form.value.code = value ? `${value}-` : ''
}})
const kindOptions: {value: MaterialSpecKind; label: string}[] = [{value:'text',label:'文字'}, {value:'number',label:'数值'}, {value:'enum',label:'选项'}, {value:'boolean',label:'是 / 否'}, {value:'date',label:'日期'}]
const optionsText = computed({get:() => fieldForm.value.options.join('\n'), set:(value: string) => {fieldForm.value.options = value.split('\n').map(entry => entry.trim()).filter(Boolean)}})
const categoryColumns = [{key:'name',title:'类别目录'}, {key:'code',title:'编码前缀'},
  {key:'status',title:'状态'}, {key:'material_count',title:'使用物料数'}, {key:'sort_order',title:'排序'}, {key:'actions',title:'操作',width:'270px'}]
const fieldColumns = [{key:'name',title:'字段名称'}, {key:'kind',title:'类型 / 单位'}, {key:'options',title:'常用选项'},
  {key:'required',title:'必填'}, {key:'enabled',title:'状态'}, {key:'sort_order',title:'排序'}, {key:'actions',title:'操作',width:'100px'}]
const auditColumns = [{key:'label',title:'调整项目'}, {key:'before',title:'修改前'}, {key:'after',title:'修改后'}]
const blocked = computed(() => busy.value || connectionLost.value || !can('catalog.manage') || !nodes.value.length)
const modalStyle = {width:'min(820px, calc(100vw - 32px))',maxHeight:'calc(100vh - 64px)',overflowY:'auto' as const}
function toggleGroup(code: string): void {
  if (filtering.value || !materialCategories.value.some(group => group.code === code)) return
  const next = new Set(collapsedGroups.value)
  if (next.has(code)) next.delete(code); else next.add(code)
  collapsedGroups.value = next
}
function expandGroups(expanded: boolean): void {
  if (!filtering.value) collapsedGroups.value = expanded ? new Set() : new Set(materialCategories.value.map(group => group.code))
}
function viewFields(code: string): void {
  if (!busy.value && !connectionLost.value && nodes.value.some(node => node.code === code && node.parent_code)) selectedCode.value = code
}
watch(() => materialCategories.value.map(group => group.code).join(','), () => {
  const existing = new Set(materialCategories.value.map(group => group.code))
  collapsedGroups.value = new Set([...collapsedGroups.value].filter(code => existing.has(code)))
})

// 本页目录窗口共用请求代次，切换入口或关闭后不得接纳迟到的目录响应。
const preparing = ref(false)
let formRead = 0
watch([showForm, showField, auditOpen], () => { if (!showForm.value && !showField.value && !auditOpen.value) { formRead++; preparing.value = false; store.cancelCatalogPreparation() } }, { flush: 'sync' })
onUnmounted(() => { formRead++; store.cancelCatalogPreparation() })
async function editCategory(code?: string, parent?: string): Promise<void> {
  if (blocked.value) return
  if (code && !nodes.value.some(node => node.code === code)) return
  if (parent && !nodes.value.some(node => node.code === parent && !node.parent_code && node.enabled)) return
  const ticket = ++formRead; preparing.value = true; showForm.value = true
  if (!await reloadMaterialCategories() || ticket !== formRead || !showForm.value) { if (ticket === formRead) { showForm.value = false; preparing.value = false }; return }
  const node = nodes.value.find(entry => entry.code === code)
  // 目录重读后目标可能已被移除或停用，不能把原来的编辑意图悄悄变成新建。
  if ((code && !node) || (parent && !nodes.value.some(entry => entry.code === parent && !entry.parent_code && entry.enabled))) {
    store.error = '类别资料已变化，请刷新目录后重试。'; showForm.value = false; preparing.value = false; return
  }
  editing.value = !!node
  form.value = node ? {code:node.code,parent_code:node.parent_code,name:node.name,enabled:node.enabled,
    sort_order:node.sort_order,notes:node.notes,version:node.version,reason:''}
    : {code:parent ? `${parent}-` : '',parent_code:parent ?? null,name:'',enabled:true,sort_order:0,notes:'',reason:''}
  preparing.value = false
}
async function saveCategory(): Promise<void> {
  if (await saveMaterialCategory({...form.value}, editing.value)) {showForm.value = false; form.value.name = ''}
}
async function editField(id?: number): Promise<void> {
  if (!selected.value || blocked.value) return
  const code = selected.value.code
  if (id && !selected.value.fields.some(field => field.id === id)) return
  const ticket = ++formRead; preparing.value = true; showField.value = true
  if (!await reloadMaterialCategories() || ticket !== formRead || !showField.value) { if (ticket === formRead) { showField.value = false; preparing.value = false }; return }
  const category = nodes.value.find(node => node.code === code && node.parent_code)
  const field = category?.fields.find(entry => entry.id === id)
  if (!category || selectedCode.value !== code || (id && !field)) {
    store.error = '子类或规格字段已变化，请重新选择后再编辑。'; showField.value = false; preparing.value = false; return
  }
  fieldForm.value = {code,field_id:field?.id,name:field?.name ?? '',kind:field?.kind ?? 'text',
    unit:field?.unit ?? '',options:field ? [...field.options] : [],allow_custom:field?.allow_custom ?? false,
    required:field?.required ?? false,enabled:field?.enabled ?? true,sort_order:field?.sort_order ?? 0,
    version:category.version,reason:''}
  preparing.value = false
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
async function history(code: string): Promise<void> {
  const node = nodes.value.find(entry => entry.code === code)
  if (!node || busy.value || connectionLost.value) return
  const ticket = ++formRead; preparing.value = true; auditOpen.value = true
  const loaded = await loadMaterialCategoryChanges(node.code)
  if (ticket !== formRead || !auditOpen.value) return
  if (loaded) auditTitle.value = `${categoryPath(node)} · 分类与模板变更`
  else auditOpen.value = false
  preparing.value = false
}
function fieldKind(field: MaterialSpecField): string {return `${kindOptions.find(option => option.value === field.kind)?.label}${field.unit ? ` / ${field.unit}` : ''}`}
</script>

<template>
  <section class="stack catalog-page">
    <p class="material-hint">大类、子类与规格模板统一维护。名称可以调整，编码前缀固定；停用限制新选择，历史物料和单据继续保留。</p>
    <p v-if="!nodes.length && materialCategories.length" class="material-hint">服务端尚未提供分类与规格模板管理，请升级 ERP 服务。</p>
    <WorkspaceTable :show-title="false" title="物料类别" :columns="categoryColumns" :data="rows" :min-table-width="1000">
      <template #actions>
        <AppButton type="button" size="small" :disabled="filtering || !materialCategories.length" @click="expandGroups(true)">展开全部</AppButton>
        <AppButton type="button" size="small" :disabled="filtering || !materialCategories.length" @click="expandGroups(false)">收起全部</AppButton>
        <AppButton v-if="can('catalog.manage') && form.name" variant="secondary" type="button" :disabled="blocked" @click.capture="captureDialogOrigin('MaterialCategoriesView:form', $event)" @click="showForm = true">继续类别草稿</AppButton>
        <AppButton v-if="can('catalog.manage') && fieldForm.name" variant="secondary" type="button" :disabled="blocked" @click.capture="captureDialogOrigin('MaterialCategoriesView:field', $event)" @click="showField = true">继续规格草稿</AppButton>
        <!-- 新建主操作统一置于辅助操作之后。 -->
        <AppButton v-if="can('catalog.manage')" variant="primary" type="button" :disabled="blocked" @click.capture="captureDialogOrigin('MaterialCategoriesView:form', $event)" @click="editCategory()">新增大类</AppButton>
      </template>
      <template #filters>
        <label class="catalog-search">搜索类别<AppInput v-model="query" aria-label="搜索类别" placeholder="类别名称、前缀或说明" /></label>
        <label class="material-category-filter">状态<WorkspaceSelect v-model="status" aria-label="筛选类别状态" :options="[{value:'all',label:'全部'}, {value:'enabled',label:'启用'}, {value:'disabled',label:'停用'}]" /></label>
      </template>
      <template #beforeTable><p v-if="filtering" class="material-hint category-tree-filter-hint">筛选时自动展开匹配路径，清空条件后恢复手动收起状态。</p></template>
      <template #cell-name="{row}"><div class="category-tree-name" :class="{'category-tree-name--child':row.depth===1}">
        <AppButton v-if="row.depth===0" variant="plain" class="category-tree-toggle" :disabled="filtering || !row.childCount" :aria-expanded="row.childCount ? row.expanded : undefined" :aria-label="`${row.expanded ? '收起' : '展开'}${row.name}子类`" @click="toggleGroup(row.code)">
          <span class="category-tree-chevron" aria-hidden="true">{{ row.childCount ? row.expanded ? '▾' : '▸' : '·' }}</span><strong>{{ row.name }}</strong>
        </AppButton>
        <strong v-else>{{ row.name }}</strong>
        <small class="category-tree-level">{{ row.depth===0 ? '大类' : '子类' }}</small>
        <p v-if="row.contextOnly" class="material-hint">匹配子类所属大类</p><p v-if="row.notes" class="material-hint">{{ row.notes }}</p>
      </div></template>
      <template #cell-status="{row}">{{ row.enabled === undefined ? '旧版目录' : row.enabled ? '启用' : '停用' }}<p v-if="row.parentEnabled===false" class="material-hint">所属大类已停用</p></template>
      <template #cell-material_count="{row}">{{ row.material_count ?? '—' }}</template>
      <template #cell-sort_order="{row}">{{ row.sort_order ?? '—' }}</template>
      <template #cell-actions="{row}"><div class="catalog-actions">
        <AppButton v-if="can('catalog.manage')" variant="text" type="button" :disabled="blocked || !row.manageable" @click.capture="captureDialogOrigin('MaterialCategoriesView:form', $event)" @click="editCategory(row.code)">编辑</AppButton>
        <AppButton v-if="!row.parent_code && can('catalog.manage')" variant="text" type="button" :disabled="blocked || !row.manageable || !row.enabled" @click.capture="captureDialogOrigin('MaterialCategoriesView:form', $event)" @click="editCategory(undefined,row.code)">新增子类</AppButton>
        <AppButton v-if="row.parent_code" variant="text" type="button" :disabled="busy || connectionLost || !row.manageable" @click="viewFields(row.code)">规格字段</AppButton>
        <AppButton variant="text" type="button" :disabled="busy || connectionLost || !row.manageable" @click.capture="captureDialogOrigin('MaterialCategoriesView:audit', $event)" @click="history(row.code)">变更记录</AppButton>
      </div></template>
      <template #empty>暂无匹配类别。</template>
    </WorkspaceTable>
    <WorkspaceTable v-if="selected" :title="`${selectedPath} · 规格模板 v${selected.template_version}`" :description="`所属子类：${selectedPath}（${selected.code}）`" :columns="fieldColumns" :data="selected.fields" :min-table-width="850">
      <template #actions>
        <AppButton v-if="can('catalog.manage')" variant="primary" type="button" :disabled="blocked" @click.capture="captureDialogOrigin('MaterialCategoriesView:field', $event)" @click="editField()">新增规格字段</AppButton>
      </template>
      <template #cell-kind="{row}">{{ fieldKind(row) }}</template>
      <template #cell-options="{row}">{{ row.options.join('、') || '—' }}<p v-if="row.allow_custom" class="material-hint">允许自定义值</p></template>
      <template #cell-required="{row}">{{ row.required ? '是' : '否' }}</template>
      <template #cell-enabled="{row}">{{ row.enabled ? '启用' : '停用' }}</template>
      <template #cell-actions="{row}"><AppButton v-if="can('catalog.manage')" variant="text" type="button" :disabled="blocked" @click.capture="captureDialogOrigin('MaterialCategoriesView:field', $event)" @click="editField(row.id)">编辑</AppButton></template>
      <template #empty>暂无规格字段，可按本类物料的实际参数新增。</template>
    </WorkspaceTable>
    <AppModal :busy="busy" origin-key="MaterialCategoriesView:form" @invalidated="showForm = false" :ready="!preparing" v-model:show="showForm" preset="card" :style="modalStyle" :mask-closable="!busy" :closable="!busy" :close-on-esc="!busy">
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
    </AppModal>
    <AppModal :busy="busy" origin-key="MaterialCategoriesView:field" @invalidated="showField = false" :ready="!preparing" v-model:show="showField" preset="card" :style="modalStyle" :mask-closable="!busy" :closable="!busy" :close-on-esc="!busy">
      <form v-if="can('catalog.manage')" class="catalog-editor" @submit.prevent="saveField">
        <h3>{{ fieldForm.field_id ? '编辑规格字段' : '新增规格字段' }} · {{ fieldCategory ? categoryPath(fieldCategory) : fieldForm.code }}</h3>
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
    </AppModal>
    <AppModal :busy="busy" origin-key="MaterialCategoriesView:audit" @invalidated="auditOpen = false" :ready="!preparing" v-model:show="auditOpen" preset="card" :style="modalStyle" :title="auditTitle">
      <article v-for="entry in auditRows" :key="entry.id" class="catalog-audit-item"><strong>{{ localTime(entry.created_at) }} · {{ entry.changed_by_name }}</strong><span>{{ entry.reason }}</span>
        <small>类别版本 {{ entry.before?.version ?? 0 }} → {{ entry.after.version }}；模板版本 {{ entry.before?.template_version ?? 0 }} → {{ entry.after.template_version }}</small>
        <NCollapse><AppCollapseItem :name="entry.id" title="查看变更前后资料"><WorkspaceTable title="分类与规格调整" :show-title="false" :columns="auditColumns" :data="materialCategoryAuditRows(entry)" :min-table-width="650"><template #empty>本次未调整类别或规格定义。</template></WorkspaceTable></AppCollapseItem></NCollapse>
      </article><p v-if="!auditRows.length" class="material-hint">初始类别由升级收录，尚无人工修改记录。</p>
    </AppModal>
  </section>
</template>

<style scoped>
/* 在共用表格内保留大类和子类的真实层级，不影响其他业务表格的单元格布局。 */
.category-tree-name { display:flex; align-items:center; flex-wrap:wrap; gap:6px 9px; min-width:0; }
.category-tree-name--child { padding-left:28px; }
.category-tree-name > .material-hint { flex-basis:100%; }
.category-tree-toggle { justify-content:flex-start; text-align:left; white-space:normal; }
.category-tree-chevron { display:inline-block; width:16px; flex-shrink:0; color:var(--workspace-field-muted); }
.category-tree-level { color:var(--workspace-field-muted); font-size:11px; }
.category-tree-filter-hint { margin-bottom:12px; }
</style>
