<script setup lang="ts">
import type { OtherInboundReopenLink } from '../../../../shared/erp-api'
import AppButton from '../app/AppButton.vue'

// 来源事件由服务端成功保存时固定；点击仅查看关联单据，不再次执行重开。
defineProps<{ links: OtherInboundReopenLink[]; currentId: number; localTime: (value: string) => string; disabled?: boolean }>()
defineEmits<{ open: [id: number] }>()
</script>

<template>
  <section v-if="links.length" class="reopen-trace" aria-label="单据重开溯源流程">
    <h3>单据溯源流程</h3>
    <ol>
      <li v-for="link in links" :key="link.id">
        <AppButton type="button" variant="text" :disabled="disabled || link.source_id === currentId"
          @click="$emit('open', link.source_id)">{{ link.source_document_no || `其他入库 #${link.source_id}` }}</AppButton>
        <span class="reopen-trace-event">
          <strong>{{ link.kind === 'reversed' ? '已冲销 → 冲销重开新单' : '已取消 → 重开为新单' }}</strong>
          <small>{{ localTime(link.created_at) }} · {{ link.created_by_name }}</small>
        </span>
        <span aria-hidden="true">→</span>
        <AppButton type="button" variant="text" :disabled="disabled || link.new_id === currentId"
          @click="$emit('open', link.new_id)">{{ link.new_document_no || `其他入库 #${link.new_id}` }}</AppButton>
      </li>
    </ol>
    <p>每张原单只能成功重开一次；新单独立审批，原单及库存历史保留。</p>
  </section>
</template>

<style scoped>
.reopen-trace { margin-bottom: 24px; padding: 16px; border: 1px solid var(--workspace-field-border); border-radius: 12px; }
.reopen-trace h3 { margin: 0 0 12px; }
.reopen-trace ol { margin: 0; padding: 0; list-style: none; }
.reopen-trace li { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.reopen-trace li + li { margin-top: 16px; }
.reopen-trace-event { display: grid; gap: 6px; }
.reopen-trace small, .reopen-trace p { color: var(--workspace-field-muted); }
.reopen-trace p { margin: 12px 0 0; }
</style>
