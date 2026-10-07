<script setup lang="ts">
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { NModal, NPopconfirm } from 'naive-ui'
import type { Material } from '../../../../../shared/erp-api'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { useLocalPagination } from '../../../composables/use-local-pagination'
import { usePiniaAppStore } from '../../../store/app-store'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import MaterialEditor from './MaterialEditor.vue'
import { materialDraft, materialInput, prepareMaterialSpecs, materialCategoryLabel, matchesMaterial } from './material-form'
import { defaultMaterialUnit } from './unit-options'
import './catalog.css'

const store = usePiniaAppStore()
const { busy, error, connectionLost, materials, materialCategories, materialUnits, suppliers, supplierMaterials, materialEditorDraft: form, materialEditingId: editingId, materialEditorOpen: showForm } = storeToRefs(store)
const { can, loadMaterial, saveMaterial, deleteMaterial } = store
const query = ref('')
const categoryFilter = ref('')
const categoryOptions = computed(() => [
  { value: '', label: '全部分类' }, { value: 'unclassified', label: '未分类' },
  ...materialCategories.value.flatMap(group => group.children.map(child => ({
    value: child.code, label: `${group.name} / ${child.name}`
  })))
])
const filtered = computed(() => materials.value.filter(item =>
  matchesMaterial(item, query.value, categoryFilter.value, materialCategories.value)))
const filterKey = computed(() => JSON.stringify([query.value, categoryFilter.value]))
// 总数按搜索结果计算；分页仅影响本页展示，不裁剪共享物料资料。
const { rows, total, page, pageSize, changePage } = useLocalPagination(filtered, filterKey)
// 物料页只声明列和业务单元格，统一由公共组件创建 vxe 表格。
const columns = [
  { key: 'sku', title: '物料编码' },
  { key: 'name', title: '物料名称' },
  { key: 'category', title: '物料分类' },
  { key: 'specification', title: '规格型号 / 封装' },
  { key: 'brand', title: '品牌 / 制造商料号' },
  { key: 'unit', title: '单位' },
  { key: 'suppliers', title: '供应商' },
  { key: 'actions', title: '操作' }
]
async function edit(item?: Material): Promise<void> {
  // 列表可能来自另一客户端修改前的快照，编辑前读取最新资料与版本。
  const latest = item ? await loadMaterial(item.id) : undefined
  if (item && !latest) return
  editingId.value = latest?.id
  form.value = materialDraft(latest)
  prepareMaterialSpecs(form.value, materialCategories.value)
  if (!latest) form.value.unit = defaultMaterialUnit(materialUnits.value)
  showForm.value = true
}
async function save(): Promise<void> {
  // 目录刷新导致选择失效时保留草稿，并显示可操作的错误提示。
  try {
    if (await saveMaterial(materialInput(form.value, !!editingId.value, materialUnits.value), editingId.value)) {showForm.value = false; editingId.value = undefined; form.value = materialDraft()}
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '物料保存失败' }
}
function supplierNames(id: number): string {
  const ids = new Set(
    supplierMaterials.value
      .filter((link) => link.material_id === id)
      .map((link) => link.supplier_id)
  )
  return (
    suppliers.value
      .filter((item) => ids.has(item.id))
      .map((item) => item.name)
      .join('、') || '未绑定'
  )
}
</script>

<template>
  <section class="stack catalog-page">
    <!-- 主标题和说明统一由工作台外壳展示。 -->
    <WorkspaceTable
      :show-title="false"
      title="物料列表"
      :columns="columns"
      :data="rows"
      :pagination="{ page, pageSize, total }"
      @page-change="changePage"
      :min-table-width="1280"
    >
      <template #actions>
        <AppButton v-if="can('catalog.manage') && (form.name || editingId) && !showForm" :disabled="busy || connectionLost" @click="showForm = true" variant="secondary" type="button">继续未保存草稿</AppButton>
        <AppButton
          v-if="can('catalog.manage')"
          :disabled="busy || connectionLost"
          @click="edit()"
          variant="primary"
          type="button"
          >新增物料</AppButton
        >
      </template>
      <template #filters>
        <label class="catalog-search"
          >搜索物料<AppInput v-model="query" placeholder="名称、编码、规格、封装或制造商料号"
        /></label>
        <label class="material-category-filter">物料分类<WorkspaceSelect v-model="categoryFilter" :options="categoryOptions" aria-label="筛选物料分类" /></label>
      </template>
      <template #beforeTable>
        <!-- 资料和供应商绑定较多，桌面端加宽；小窗口仍保留两侧各 16px 的边距。 -->
        <NModal
          v-model:show="showForm"
          preset="card"
          :mask-closable="!busy"
          :closable="!busy"
          :close-on-esc="!busy"
          :style="{
            width: 'min(1200px, calc(100vw - 32px))',
            maxHeight: 'calc(100vh - 48px)',
            overflowY: 'auto'
          }"
        >
          <!-- 原生表单校验与中文分组在编辑器中，页面只连接状态和保存动作。 -->
          <MaterialEditor
            :units="materialUnits"
            :suppliers="suppliers"
            v-if="showForm && can('catalog.manage')" :form="form" :categories="materialCategories"
            :editing="!!editingId" :busy="busy" :disconnected="connectionLost"
            @save="save" @cancel="showForm = false"
          />
        </NModal>
      </template>
      <template #cell-category="{ row }">{{ materialCategoryLabel(row.category_code, materialCategories) }}</template>
      <template #cell-specification="{ row }"><div>{{ row.spec_summary || row.specification || '未填写' }}</div><span class="material-hint">{{ row.package }}</span></template>
      <template #cell-brand="{ row }"><div>{{ row.brand || '未填写' }}</div><span class="material-hint">{{ row.manufacturer_part_number }}</span></template>
      <template #cell-suppliers="{ row }">{{ supplierNames(row.id) }}</template>
      <template #cell-actions="{ row }">
        <div class="catalog-actions" v-if="can('catalog.manage')">
          <AppButton
            :disabled="busy || connectionLost"
            @click="edit(row)"
            variant="text"
            type="button"
            >编辑</AppButton
          >
          <NPopconfirm
            positive-text="确认"
            negative-text="取消"
            @positive-click="deleteMaterial(row.id)"
          >
            <template #trigger
              ><AppButton :disabled="busy || connectionLost" variant="text" type="button"
                >删除</AppButton
              ></template
            >
            确认删除“{{ row.name }}”？关联的供货关系将一并移除。已被业务记录引用的资料不能删除。
          </NPopconfirm>
        </div>
      </template>
      <template #empty>{{ query || categoryFilter ? '没有匹配的物料。' : '暂无物料，请先新增。' }}</template>
    </WorkspaceTable>
  </section>
</template>
