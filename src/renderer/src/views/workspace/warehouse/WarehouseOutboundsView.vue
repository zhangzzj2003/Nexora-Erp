<script setup lang="ts">
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { NModal } from 'naive-ui'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { submitCreateDialog } from '../../../utils/create-dialog'

const store = usePiniaAppStore()
const { error, notice, busy, connectionLost, materials, warehouses, warehouseOutbounds, otherOutboundForm,
  otherOutboundReversalReasons } = storeToRefs(store)
const { can, localTime, createOtherOutbound, postWarehouseOutbound, cancelOtherOutbound,
  reverseOtherOutbound } = store
const showForm = ref(false)
const query = ref('')
const filtered = computed(() => warehouseOutbounds.value.filter((item) =>
  [item.id, item.reference, item.warehouse_name, item.note, ...item.lines.map((line) => line.material_name)]
    .join(' ').toLowerCase().includes(query.value.trim().toLowerCase())))
const reasonName = { scrap: '报废', sample: '样品', other: '其他', purchase_return: '采购退货' }
const columns = [
  { key: 'document', title: '单据' }, { key: 'source', title: '仓库与来源' },
  { key: 'lines', title: '物料明细' }, { key: 'actions', title: '操作' }
]
// 写入失败时保留表单，成功后才关闭弹窗。
async function submitCreate(): Promise<void> {
  await submitCreateDialog(createOtherOutbound, { busy, error, notice }, showForm)
}
</script>

<template>
  <section class="stack">
    <WorkspaceTable dataset="warehouseOutbounds" :query="query"
      :show-title="false"
      :data="filtered"
      title="仓库出库"
      :columns="columns"
      :min-table-width="900"
    >
      <template #actions>
        <AppButton
          v-if="can('other_outbound.create')"
          :disabled="busy || connectionLost"
          @click="showForm = true"
          variant="primary"
          type="button"
          >新建仓库出库</AppButton
        >
      </template>
      <template #filters>
        <label>搜索出库单<AppInput v-model="query" placeholder="单号、仓库或物料" /></label>
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
            v-if="showForm && can('other_outbound.create')"
            class="stack"
            @submit.prevent="submitCreate"
          >
            <h3>其他用途出库</h3>
            <div class="form-grid">
              <label
                >仓库<WorkspaceSelect remote-dataset="warehouses"
                  v-model="otherOutboundForm.warehouse_id"
                  required
                  :options="[...warehouses.map((item) => ({ label: item.name, value: item.id }))]"
              /></label>
              <label
                >用途<WorkspaceSelect
                  v-model="otherOutboundForm.reason"
                  required
                  :options="[
                    { label: '报废', value: 'scrap' },
                    { label: '样品', value: 'sample' },
                    { label: '其他', value: 'other' }
                  ]"
              /></label>
              <label
                >参考号<AppInput v-model.trim="otherOutboundForm.reference" maxlength="100"
              /></label>
              <label
                >出库说明<AppInput v-model.trim="otherOutboundForm.note" required maxlength="200"
              /></label>
            </div>
            <div v-for="(line, index) in otherOutboundForm.lines" :key="index" class="line-row">
              <label
                >物料<WorkspaceSelect remote-dataset="materials"
                  v-model="line.material_id"
                  required
                  :options="[
                    { label: '选择物料', value: 0, disabled: true },
                    ...materials.map((item) => ({
                      label: (item.sku + ' · ' + item.name).trim(),
                      value: item.id
                    }))
                  ]"
              /></label>
              <label
                >数量<AppInput
                  v-model.trim="line.quantity"
                  type="number"
                  min="0.001"
                  max="1000000"
                  step="0.001"
                  required
              /></label>
              <AppButton
                type="button"
                :disabled="otherOutboundForm.lines.length === 1"
                @click="otherOutboundForm.lines.splice(index, 1)"
                variant="text"
                >移除</AppButton
              >
            </div>
            <div class="form-actions">
              <AppButton
                type="button"
                @click="otherOutboundForm.lines.push({ material_id: 0, quantity: '1' })"
                variant="secondary"
                >添加明细</AppButton
              >
              <AppButton :disabled="busy || connectionLost" variant="primary" type="submit"
                >保存草稿</AppButton
              >
              <AppButton type="button" @click="showForm = false" variant="secondary"
                >收起</AppButton
              >
            </div>
            <p class="muted">确认后才扣减库存；其他出库不产生采购应付。</p>
          </form>
        </NModal>
      </template>
      <template #cell-document="{ row: item }"
        ><strong>#{{ item.id }}</strong
        ><small>{{ localTime(item.created_at) }} · {{ item.created_by_name }}</small
        ><small>{{
          item.status === 'draft'
            ? '待确认'
            : item.status === 'cancelled'
              ? '已取消'
              : item.reversal_id
                ? '已冲销'
                : '已出库'
        }}</small></template
      >
      <template #cell-source="{ row: item }"
        >{{ item.warehouse_name }} · {{ reasonName[item.reason] }}<small>{{ item.note }}</small
        ><small v-if="item.reference">{{ item.reference }}</small
        ><small v-if="item.purchase_return_id"
          >采购退货单 #{{ item.purchase_return_id }}</small
        ></template
      >
      <template #cell-lines="{ row: item }"
        ><div v-for="line in item.lines" :key="line.id">
          {{ line.material_name }} × {{ line.quantity }} {{ line.unit }}
        </div></template
      >
      <template #cell-actions="{ row: item }"
        ><div class="form-actions">
          <AppButton
            v-if="item.status === 'draft' && can('other_outbound.post')"
            :disabled="busy || connectionLost"
            @click="postWarehouseOutbound(item.id)"
            variant="primary"
            size="small"
            type="button"
            >确认出库</AppButton
          >
          <AppButton
            v-if="
              item.status === 'draft' &&
              item.source_kind === 'other' &&
              can('other_outbound.cancel')
            "
            :disabled="busy || connectionLost"
            @click="cancelOtherOutbound(item.id)"
            variant="secondary"
            size="small"
            type="button"
            >取消</AppButton
          >
        </div>
        <form
          v-if="
            item.status === 'posted' &&
            !item.reversal_id &&
            item.source_kind === 'other' &&
            can('other_outbound.reverse')
          "
          class="inline-form"
          @submit.prevent="reverseOtherOutbound(item.id)"
        >
          <label
            >冲销原因<AppInput
              v-model.trim="otherOutboundReversalReasons[item.id]"
              required
              maxlength="200"
          /></label>
          <AppButton
            :disabled="busy || connectionLost"
            variant="secondary"
            size="small"
            type="submit"
            >冲销</AppButton
          >
        </form>
        <small v-if="item.reversal_reason">冲销：{{ item.reversal_reason }}</small></template
      >
      <template #empty>{{ query ? '没有匹配的出库单。' : '暂无仓库出库单。' }}</template>
    </WorkspaceTable>
  </section>
</template>
