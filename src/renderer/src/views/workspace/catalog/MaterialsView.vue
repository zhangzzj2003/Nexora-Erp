<script setup lang="ts">
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
import { computed, reactive, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { NModal, NPopconfirm } from 'naive-ui'
import type { Material } from '../../../../../shared/erp-api'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import './catalog.css'

const store = usePiniaAppStore()
const { busy, connectionLost, materials, suppliers, supplierMaterials } = storeToRefs(store)
const { can, saveMaterial, deleteMaterial } = store
const query = ref('')
const editingId = ref<number | undefined>()
const showForm = ref(false)
const form = reactive({ sku: '', name: '', unit: '件' })
const filtered = computed(() =>
  materials.value.filter((item) =>
    [item.sku, item.name, item.unit]
      .join(' ')
      .toLowerCase()
      .includes(query.value.trim().toLowerCase())
  )
)
// 物料页只声明列和业务单元格，统一由公共组件创建 vxe 表格。
const columns = [
  { key: 'sku', title: '物料编码' },
  { key: 'name', title: '名称（可包含规格型号）' },
  { key: 'unit', title: '单位' },
  { key: 'suppliers', title: '供应商' },
  { key: 'actions', title: '操作' }
]
function edit(item?: Material): void {
  editingId.value = item?.id
  Object.assign(
    form,
    item ? { sku: item.sku, name: item.name, unit: item.unit } : { sku: '', name: '', unit: '件' }
  )
  showForm.value = true
}
async function save(): Promise<void> {
  if (await saveMaterial({ ...form }, editingId.value)) showForm.value = false
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
    <WorkspaceTable dataset="materials" :query="query"
      :show-title="false"
      title="物料列表"
      :columns="columns"
      :data="filtered"
      :min-table-width="680"
    >
      <template #actions>
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
          >搜索物料<AppInput v-model="query" placeholder="输入名称或编码搜索"
        /></label>
        <span class="muted">共 {{ materials.length }} 条</span>
      </template>
      <template #beforeTable>
        <NModal
          v-model:show="showForm"
          preset="card"
          :mask-closable="!busy"
          :style="{
            width: 'min(900px, calc(100vw - 32px))',
            maxHeight: 'calc(100vh - 48px)',
            overflowY: 'auto'
          }"
        >
          <form
            v-if="showForm && can('catalog.manage')"
            class="catalog-editor"
            @submit.prevent="save"
          >
            <h3>{{ editingId ? '编辑物料' : '新增物料' }}</h3>
            <div class="form-grid">
              <label>物料编码<AppInput v-model.trim="form.sku" required maxlength="40" /></label>
              <label
                >名称（可包含规格型号）<AppInput v-model.trim="form.name" required maxlength="120"
              /></label>
              <label>单位<AppInput v-model.trim="form.unit" required maxlength="20" /></label>
            </div>
            <div class="form-actions">
              <AppButton :disabled="busy || connectionLost" variant="primary" type="submit"
                >保存</AppButton
              ><AppButton
                type="button"
                :disabled="busy"
                @click="showForm = false"
                variant="secondary"
                >取消</AppButton
              >
            </div>
          </form>
        </NModal>
      </template>
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
      <template #empty>{{ query ? '没有匹配的物料。' : '暂无物料，请先新增。' }}</template>
    </WorkspaceTable>
  </section>
</template>
