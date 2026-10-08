<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { DocumentApprovalRecord } from '../../../../shared/document-approval-api'
import type { Role } from '../../../../shared/erp-api'
import { documentApprovalProgress } from '../../utils/document-approval-progress'
import { documentApprovalStepAction, documentApprovalStepLabels } from '../../../../shared/document-approval-api'

// 顶部流程只展示服务端进度，不提供跳步、批准或执行入口。
const props = defineProps<{
  record: DocumentApprovalRecord
  roles: readonly Pick<Role, 'code' | 'label'>[]
  localTime: (value: string) => string
}>()
const progress = computed(() => documentApprovalProgress(props.record))
const flowViewport = ref<HTMLElement | null>(null)
// 只调整流程自己的横向位置，不让步骤变化把单据正文或整个窗口滚走。
watch(() => [props.record.document_type, props.record.document_id, props.record.intent,
  props.record.generation, props.record.current_step, props.record.status], async () => {
  await nextTick()
  const viewport = flowViewport.value
  // 查看驳回、撤回或已执行记录时也定位到结果节点，避免窄窗口把结果藏在轨道末端。
  const current = viewport?.querySelector<HTMLElement>('[aria-current="step"], .is-rejected, .is-withdrawn')
    ?? (props.record.status === 'executed' ? viewport?.querySelector<HTMLElement>('li:last-child') : null)
  if (!viewport || !current) return
  viewport.scrollTo({ left: Math.max(0, current.offsetLeft - (viewport.clientWidth - current.clientWidth) / 2),
    behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' })
}, { immediate: true, flush: 'post' })
</script>

<template>
  <section class="approval-progress" aria-label="审批进度">
    <div class="approval-progress-heading">
      <h3>审批进度</h3>
      <span class="approval-status" :class="`is-${record.status}`">{{ progress.label }}</span>
      <small v-if="progress.nodes.length" class="approval-version">审批版本 {{ record.version }}<template v-if="record.generation"> · 第 {{ record.generation }} 次送审</template></small>
    </div>
    <p class="approval-progress-summary" role="status" aria-live="polite">{{ progress.summary }}</p>
    <!-- 所有窗口都保留横向流程；独立滚动区域支持键盘，节点同时保留文字状态。 -->
    <div v-if="progress.nodes.length" ref="flowViewport" class="approval-flow-viewport" tabindex="0"
      role="region" aria-label="审批流程（可左右滚动）">
      <ol class="approval-flow" aria-label="送审、审批与业务执行流程"
        :style="{ '--node-count': progress.nodes.length, '--node-width': progress.nodes.length > 3 ? '148px' : '112px' }">
        <li v-for="(node, index) in progress.nodes" :key="`${record.generation}:${node.key}`" :class="`is-${node.state}`"
          :style="{ '--node-index': index }" :aria-current="node.state === 'current' ? 'step' : undefined">
          <span class="approval-node-marker" aria-hidden="true">
            <!-- 线性图标表示实际节点职责，完成/驳回/撤回通过角标表示，避免图标含义随状态丢失。 -->
            <svg class="approval-stage-icon" viewBox="0 0 24 24">
              <template v-if="node.key === 'submit'">
                <path d="m21 3-7 18-4-7-7-4 18-7Z" /><path d="m10 14 5-5" />
              </template>
              <template v-else-if="node.key === 'execute'">
                <path d="m3 9 9-6 9 6v11H3V9Z" /><path d="M8 20v-8h8v8M8 16h8M3 9h18" />
              </template>
              <template v-else-if="node.name.includes('财务')">
                <circle cx="12" cy="12" r="9" /><path d="m8 7 4 5 4-5M8 12h8M8 15h8M12 12v6" />
              </template>
              <template v-else-if="node.name.includes('批准')">
                <path d="m12 3 2.7 1.5 3.1.3.7 3 2 2.4-1 2.9.2 3.1-2.8 1.3-1.9 2.4-3-.6-3 .6-1.9-2.4-2.8-1.3.2-3.1-1-2.9 2-2.4.7-3 3.1-.3L12 3Z" /><path d="m8.5 12 2.3 2.3 4.7-4.6" />
              </template>
              <template v-else-if="node.name.includes('核准') || node.name.includes('复核')">
                <path d="m12 3 8 3v6c0 4-3.5 7-8 9-4.5-2-8-5-8-9V6l8-3Z" /><path d="m8.5 12 2.3 2.3 4.7-4.6" />
              </template>
              <template v-else>
                <path d="M8 5H6a2 2 0 0 0-2 2v13a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V7a2 2 0 0 0-2-2h-2" /><rect x="8" y="3" width="8" height="4" rx="1" /><path d="m8 14 2.5 2.5L16 11" />
              </template>
            </svg>
            <span v-if="['completed', 'rejected', 'withdrawn'].includes(node.state)" class="approval-node-badge">
              <svg viewBox="0 0 16 16">
                <path v-if="node.state === 'completed'" d="m4 8 2.5 2.5L12 5" />
                <path v-else-if="node.state === 'rejected'" d="m5 5 6 6m0-6-6 6" />
                <path v-else d="M4 8h8" />
              </svg>
            </span>
          </span>
          <div class="approval-node-copy">
            <div class="approval-node-title"><strong>{{ node.name }}</strong><span>{{ node.caption }}</span></div>
            <small v-if="node.event">{{ node.event.actor_name }} · {{ localTime(node.event.created_at) }}</small>
            <small v-else-if="node.key.startsWith('step-')">由有{{ documentApprovalStepLabels[documentApprovalStepAction(record.steps[Number(node.key.slice(5))]!)] }}权限的人员处理</small>
          </div>
        </li>
      </ol>
    </div>
    <div v-if="progress.nodes.length" class="approval-progress-note">
      <span v-if="record.steps.length">{{ progress.completed }} / {{ record.steps.length }} 步审批已完成</span>
      <span>各步骤按角色的按钮权限操作；同一人员可完成多个已授权步骤。批准后仍需执行对应业务操作。</span>
    </div>
  </section>
</template>

<style scoped>
/* 沿用弹窗主题与应用强调色，流程作为顶部的一块紧凑信息区。 */
.approval-progress { margin-bottom: 22px; padding: 20px 22px 16px; border: 1px solid var(--workspace-field-border);
  border-radius: 14px; background: var(--app-modal-surface); color: var(--workspace-field-text); overflow-wrap: anywhere;
  --approval-danger: #b94438; }
:root[data-theme='dark'] .approval-progress { --approval-danger: #ffaaa2; }
.approval-progress-heading { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.approval-progress-heading h3 { margin: 0; font-size: 15px; }
.approval-status { padding: 3px 9px; border-radius: 6px; background: var(--app-accent-tint); color: var(--workspace-field-accent); font-size: 12px; font-weight: 600; }
.approval-status.is-rejected { color: var(--approval-danger); background: color-mix(in srgb, var(--approval-danger) 10%, transparent); }
.approval-status.is-draft, .approval-status.is-withdrawn { color: var(--workspace-field-muted); background: var(--workspace-field-disabled); }
.approval-version { margin-left: auto; color: var(--workspace-field-muted); font-size: 12px; }
.approval-progress-summary { margin: 12px 0 0; font-size: 13px; line-height: 1.6; }
/* 步骤多少决定轨道最小宽度；窄窗口横向滚动，绝不改为纵向排列。 */
.approval-flow-viewport { margin: 8px -6px 12px; overflow-x: auto; overflow-y: hidden; scrollbar-width: thin;
  scrollbar-color: var(--workspace-field-border) transparent; border-radius: 8px; }
.approval-flow-viewport:focus-visible { outline: none; box-shadow: inset 0 -2px var(--workspace-field-accent); }
.approval-flow { position: relative; display: flex; flex-direction: row; list-style: none; padding: 14px 6px 12px; margin: 0;
  width: max(100%, calc(var(--node-count) * var(--node-width))); }
.approval-flow li { position: relative; flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: center; gap: 14px;
  color: var(--workspace-field-muted); animation: approval-node-enter 420ms cubic-bezier(.16, 1, .3, 1) both;
  animation-delay: calc(var(--node-index) * 65ms); }
/* 灰线表示尚未办理，强调色线表示已经完成；当前连线的微光不代表未来步骤已完成。 */
.approval-flow li:not(:last-child)::before, .approval-flow li:not(:last-child)::after {
  content: ''; position: absolute; top: 23px; left: calc(50% + 32px); width: calc(100% - 64px); height: 2px;
  border-radius: 2px; background: var(--workspace-field-border); transform-origin: left; }
.approval-flow li:not(:last-child)::after { background: var(--workspace-field-accent); transform: scaleX(0);
  transition: transform 450ms cubic-bezier(.16, 1, .3, 1); }
.approval-flow li.is-completed:not(:last-child)::after { transform: scaleX(1); animation: approval-link-enter 500ms cubic-bezier(.16, 1, .3, 1) both;
  animation-delay: calc(var(--node-index) * 65ms + 180ms); }
.approval-flow li.is-current:not(:last-child)::after { transform: scaleX(.35); background: linear-gradient(90deg, var(--workspace-field-accent), transparent);
  animation: approval-link-glow 2800ms ease-in-out infinite; }
.approval-node-marker { position: relative; display: grid; place-items: center; flex: none; width: 48px; height: 48px;
  border: 1px solid var(--workspace-field-border); border-radius: 50%; background: var(--app-modal-surface);
  transition: color 220ms ease, border-color 220ms ease, background 220ms ease; }
.approval-stage-icon { width: 25px; height: 25px; fill: none; stroke: currentColor; stroke-width: 1.65; stroke-linecap: round; stroke-linejoin: round; }
.is-completed .approval-node-marker { color: var(--workspace-field-accent); border-color: color-mix(in srgb, var(--workspace-field-accent) 45%, var(--workspace-field-border));
  background: linear-gradient(145deg, var(--app-accent-active-tint), var(--app-accent-tint)); }
.is-current .approval-node-marker { border: 2px solid var(--workspace-field-accent); color: var(--workspace-field-accent);
  background: var(--app-accent-tint); box-shadow: 0 4px 14px var(--app-accent-ring); }
/* 仅当前待办使用缓慢光圈，帮助定位；停止/完成状态没有持续动效。 */
.is-current .approval-node-marker::after { content: ''; position: absolute; inset: -6px; border: 1px solid var(--workspace-field-accent);
  border-radius: 50%; pointer-events: none; animation: approval-current-pulse 2800ms ease-out infinite; }
.is-rejected .approval-node-marker { border-color: var(--approval-danger); color: var(--approval-danger); }
.is-withdrawn .approval-node-marker { border-style: dashed; }
.approval-node-badge { position: absolute; right: -2px; bottom: -2px; display: grid; place-items: center; width: 18px; height: 18px;
  border: 2px solid var(--app-modal-surface); border-radius: 50%; background: var(--workspace-field-accent); color: var(--app-modal-background); }
.is-rejected .approval-node-badge { background: var(--approval-danger); }
.is-withdrawn .approval-node-badge { background: var(--workspace-field-muted); }
.approval-node-badge svg { width: 12px; height: 12px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.approval-node-copy { padding: 0 10px; width: 100%; text-align: center; }
.approval-node-title { display: flex; flex-direction: column; align-items: center; gap: 4px; line-height: 1.6; }
.approval-node-title strong { font-size: 14px; font-weight: 600; color: var(--workspace-field-text); }
.approval-node-title > span { font-size: 12px; }
.is-current .approval-node-title strong, .is-current .approval-node-title > span { color: var(--workspace-field-accent); }
.is-rejected .approval-node-title > span { color: var(--approval-danger); }
.approval-node-copy small { display: block; margin-top: 4px; font-size: 12px; line-height: 1.6; }
@keyframes approval-node-enter { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
@keyframes approval-link-enter { from { transform: scaleX(0); } to { transform: scaleX(1); } }
@keyframes approval-current-pulse { 0% { opacity: .5; transform: scale(.94); } 75%, 100% { opacity: 0; transform: scale(1.24); } }
@keyframes approval-link-glow { 0%, 100% { opacity: .35; } 50% { opacity: .9; } }
/* 尊重系统减少动态效果设置；状态图标和完成连线保持可读，不依赖动画表达结果。 */
@media (prefers-reduced-motion: reduce) {
  .approval-flow li, .approval-flow li::after, .approval-node-marker::after { animation: none !important; }
  .approval-flow li::after, .approval-node-marker { transition: none; }
  .is-current .approval-node-marker::after { opacity: .25; }
}
.approval-progress-note { display: flex; flex-wrap: wrap; gap: 6px 18px; padding-top: 12px; border-top: 1px solid var(--workspace-field-border);
  color: var(--workspace-field-muted); font-size: 12px; line-height: 1.6; }
.approval-progress-note > span:first-child:not(:last-child) { flex: none; color: var(--workspace-field-accent); }
@media (max-width: 650px) {
  .approval-progress { padding: 16px; }
  .approval-version { width: 100%; margin-left: 0; }
}
</style>
