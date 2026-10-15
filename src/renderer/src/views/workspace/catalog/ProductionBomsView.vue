<script setup lang="ts">
// 列表和产品详情复用同一 BOM 编辑器、详情及原有版本操作。
import { computed, ref } from 'vue'
import { captureDialogOrigin } from '../../../utils/dialog-origin'
import AppInput from '../../../components/app/AppInput.vue'
import AppButton from '../../../components/app/AppButton.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import BomEditor from './BomEditor.vue'
import BomDetailDialog from './BomDetailDialog.vue'
import { recordColumns, matchesRecordQuery } from '../../../utils/workspace-records'
import { useAppStore } from '../../../store/app-store'
const {busy, connectionLost, boms, can, localTime, activateBom, retireBom, cancelBom, prepareProductBom, openBomDetail} = useAppStore()
const createOpen = ref(false)
const recordQuery = ref('')
const filteredRecords = computed(() => boms.value.filter(item => matchesRecordQuery(recordQuery.value,
  [item.id, item.product_name, item.product_sku, item.created_by_name, ...item.lines.map(line => line.material_name)])))
function copyBom(item: typeof boms.value[number]): void {
  if (prepareProductBom(item.product_material_id, item)) createOpen.value = true
}
</script>

<template>
  <section class="stack">
    <!-- 业务草稿仍由 Pinia 保存，公共弹窗只负责布局和交互边界。 -->
    <BomEditor v-model:show="createOpen" />
    <BomDetailDialog />
    <!-- 主标题由工作台提供，列表复用仓库管理的筛选区、状态和单元格布局。 -->
    <WorkspaceTable
      :show-title="false"
      title="生产 BOM"
      :data="filteredRecords"
      :columns="recordColumns"
      :min-table-width="1100"
    >
      <template #actions>
        <AppButton
          v-if="can('bom.create')"
          type="button"
          :disabled="busy || connectionLost"
          @click.capture="captureDialogOrigin('ProductionBomsView:form', $event)" @click="createOpen = true"
          variant="primary"
        >
          新建 BOM 版本
        </AppButton>
      </template>
      <template #filters>
        <label>
          搜索生产 BOM
          <AppInput v-model="recordQuery" placeholder="单号、名称或物料" />
        </label>
      </template>

      <template #cell-document="{ row: item }">
        <div>
          <strong>
            #{{ item.id }} · {{ item.product_name }}（{{ item.product_sku }}）· V{{ item.version }}
          </strong>
          <p class="muted">
            {{ localTime(item.created_at) }} · 创建人 {{ item.created_by_name }} · 基准产出
            {{ item.base_quantity }}
            {{ item.product_unit }}
            <span v-if="item.note">· {{ item.note }}</span>
          </p>
        </div>
      </template>
      <template #cell-status="{ row: item }">
        <span class="pill" :class="item.status">
          {{
            {
              draft: '草稿',
              active: '已启用',
              retired: '已停用',
              cancelled: '已取消'
            }[item.status]
          }}
        </span>
      </template>
      <template #cell-details="{ row: item }">
        <AppButton v-if="item.source_bom" size="small" :disabled="busy || connectionLost" @click="openBomDetail(item.source_bom.id)">来源：{{ item.source_bom.product_name }} · V{{ item.source_bom.version }}</AppButton>
        <div class="workspace-record-lines">
          <span v-for="line in item.lines" :key="line.id">
            {{ line.material_name }} × {{ line.quantity }} {{ line.unit }}
          </span>
        </div>
      </template>
      <template #cell-actions="{ row: item }">
        <div class="form-actions">
          <AppButton size="small" :disabled="busy || connectionLost" @click="openBomDetail(item.id)">详情</AppButton>
          <AppButton v-if="item.status !== 'cancelled' && can('bom.create')" size="small" :disabled="busy || connectionLost" @click="copyBom(item)">复制派生</AppButton>
          <AppButton
            v-if="item.status === 'draft' && can('bom.activate')"
            type="button"
            :disabled="
              busy || connectionLost ||
              boms.some(
                (other) =>
                  other.product_material_id === item.product_material_id &&
                  other.status === 'active'
              )
            "
            @click="activateBom(item.id)"
            variant="primary"
            size="small"
          >
            启用
          </AppButton>
          <AppButton
            v-if="item.status === 'active' && can('bom.retire')"
            type="button"
            :disabled="busy || connectionLost"
            @click="retireBom(item.id)"
            variant="secondary"
            size="small"
          >
            停用
          </AppButton>
          <AppButton
            v-if="item.status === 'draft' && can('bom.cancel')"
            type="button"
            :disabled="busy || connectionLost"
            @click="cancelBom(item.id)"
            variant="secondary"
            size="small"
          >
            取消草稿
          </AppButton>
        </div>
      </template>
      <template #empty>
        <strong>{{ recordQuery ? '没有匹配的记录' : '暂无生产 BOM记录' }}</strong>
        <span>
          {{
            recordQuery
              ? '可调整单号、名称或物料关键词后重新搜索。'
              : '业务记录生成后，可在这里查看明细与处理状态。'
          }}
        </span>
      </template>
    </WorkspaceTable>
  </section>
</template>

<style scoped>
/* 成品资料卡展开时，同行数量输入框保持正常高度，避免随资料卡一起拉伸。 */
.bom-basic-field { align-content: start; }
</style>
