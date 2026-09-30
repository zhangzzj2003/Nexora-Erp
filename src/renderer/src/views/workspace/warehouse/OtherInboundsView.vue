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
const { error, notice, busy, connectionLost, materials, warehouses, otherInbounds, otherInboundForm,
  otherInboundReversalReasons } = storeToRefs(store)
const { can, localTime, createOtherInbound, postOtherInbound, cancelOtherInbound,
  reverseOtherInbound } = store
const showForm = ref(false)
const query = ref('')
const filtered = computed(() => otherInbounds.value.filter((item) =>
  [item.id, item.reference, item.warehouse_name, item.note, ...item.lines.map((line) => line.material_name)]
    .join(' ').toLowerCase().includes(query.value.trim().toLowerCase())))
const reasonName = { opening: '期初补录', gift: '赠品', other: '其他' }
const columns = [
  { key: 'document', title: '单据' }, { key: 'source', title: '仓库与来源' },
  { key: 'lines', title: '物料明细' }, { key: 'actions', title: '操作' }
]
// 写入失败时保留表单，成功后才关闭弹窗。
async function submitCreate(): Promise<void> {
  await submitCreateDialog(createOtherInbound, { busy, error, notice }, showForm)
}
</script>

<template>
  <section class="stack">
    <WorkspaceTable dataset="otherInbounds" :query="query"
      :show-title="false"
      :data="filtered"
      title="其他入库"
      :columns="columns"
      :min-table-width="900"
    >
      <template #actions>
        <AppButton
          v-if="can('other_inbound.create')"
          :disabled="busy || connectionLost"
          @click="showForm = true"
          variant="primary"
          type="button"
          >新建其他入库</AppButton
        >
      </template>
      <template #filters>
        <label>搜索入库单<AppInput v-model="query" placeholder="单号、仓库或物料" /></label>
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
            v-if="showForm && can('other_inbound.create')"
            class="stack"
            @submit.prevent="submitCreate"
          >
            <h3>非采购来源入库</h3>
            <div class="form-grid">
              <label
                >仓库<WorkspaceSelect remote-dataset="warehouses"
                  v-model="otherInboundForm.warehouse_id"
                  required
                  :options="[...warehouses.map((item) => ({ label: item.name, value: item.id }))]"
              /></label>
              <label
                >用途<WorkspaceSelect
                  v-model="otherInboundForm.reason"
                  required
                  :options="[
                    { label: '期初补录', value: 'opening' },
                    { label: '赠品', value: 'gift' },
                    { label: '其他', value: 'other' }
                  ]"
              /></label>
              <label
                >参考号<AppInput v-model.trim="otherInboundForm.reference" maxlength="100"
              /></label>
              <label
                >入库说明<AppInput v-model.trim="otherInboundForm.note" required maxlength="200"
              /></label>
            </div>
            <div v-for="(line, index) in otherInboundForm.lines" :key="index" class="line-row">
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
                :disabled="otherInboundForm.lines.length === 1"
                @click="otherInboundForm.lines.splice(index, 1)"
                variant="text"
                >移除</AppButton
              >
            </div>
            <div class="form-actions">
              <AppButton
                type="button"
                @click="otherInboundForm.lines.push({ material_id: 0, quantity: '1' })"
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
            <p class="muted">确认后才增加库存；这类入库不产生采购应付。</p>
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
                : '已入库'
        }}</small></template
      >
      <template #cell-source="{ row: item }"
        >{{ item.warehouse_name }} · {{ reasonName[item.reason] }}<small>{{ item.note }}</small
        ><small v-if="item.reference">{{ item.reference }}</small></template
      >
      <template #cell-lines="{ row: item }"
        ><div v-for="line in item.lines" :key="line.id">
          {{ line.material_name }} × {{ line.quantity }} {{ line.unit }}
        </div></template
      >
      <template #cell-actions="{ row: item }"
        ><div class="form-actions">
          <AppButton
            v-if="item.status === 'draft' && can('other_inbound.post')"
            :disabled="busy || connectionLost"
            @click="postOtherInbound(item.id)"
            variant="primary"
            size="small"
            type="button"
            >确认入库</AppButton
          >
          <AppButton
            v-if="item.status === 'draft' && can('other_inbound.cancel')"
            :disabled="busy || connectionLost"
            @click="cancelOtherInbound(item.id)"
            variant="secondary"
            size="small"
            type="button"
            >取消</AppButton
          >
        </div>
        <form
          v-if="item.status === 'posted' && !item.reversal_id && can('other_inbound.reverse')"
          class="inline-form"
          @submit.prevent="reverseOtherInbound(item.id)"
        >
          <label
            >冲销原因<AppInput
              v-model.trim="otherInboundReversalReasons[item.id]"
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
      <template #empty>{{ query ? '没有匹配的入库单。' : '暂无其他入库单。' }}</template>
    </WorkspaceTable>
  </section>
</template>
