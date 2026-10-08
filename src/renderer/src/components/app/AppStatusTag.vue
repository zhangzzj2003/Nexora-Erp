<script lang="ts">
// 组件只约定展示语义，各业务页面负责将自己的状态映射为标签文字和色调。
export type AppStatusTone = 'success' | 'pending' | 'info' | 'ready' | 'danger' | 'neutral' | 'reversed'
</script>

<script setup lang="ts">
withDefaults(defineProps<{ label: string; tone?: AppStatusTone }>(), { tone: 'neutral' })
</script>

<template>
  <!-- 完整文字表达状态；圆点仅作装饰，不让辅助技术重复朗读。 -->
  <span class="app-status-tag" :class="`app-status-tag--${tone}`">
    <span class="app-status-tag__dot" aria-hidden="true"></span>{{ label }}
  </span>
</template>

<style scoped>
/* 状态使用轻底色胶囊和同色圆点突出，静态展示避免业务列表持续闪动。 */
.app-status-tag {
  display: inline-flex; align-self: flex-start; align-items: center; gap: 6px; min-height: 26px; padding: 3px 9px;
  border: 1px solid color-mix(in srgb, var(--app-status-tag-color) 30%, transparent);
  border-radius: 999px; color: var(--app-status-tag-color);
  background: color-mix(in srgb, var(--app-status-tag-color) 11%, transparent);
  font-size: 12px; font-weight: 600; line-height: 18px; white-space: nowrap;
}
.app-status-tag__dot {
  width: 6px; height: 6px; flex: 0 0 6px; border-radius: 50%; background: currentColor;
  box-shadow: 0 0 0 3px color-mix(in srgb, currentColor 12%, transparent);
}
.app-status-tag--success { --app-status-tag-color: #16734d; }
.app-status-tag--pending { --app-status-tag-color: #946000; }
.app-status-tag--info { --app-status-tag-color: #2963b6; }
.app-status-tag--ready { --app-status-tag-color: #087684; }
.app-status-tag--danger { --app-status-tag-color: #bb3650; }
.app-status-tag--neutral { --app-status-tag-color: #626d7e; }
.app-status-tag--reversed { --app-status-tag-color: #7851ad; }
/* 深色主题提升文字亮度，底色与边框仍由同一状态色生成，保证两种主题语义一致。 */
:root[data-theme='dark'] .app-status-tag--success { --app-status-tag-color: #69d8aa; }
:root[data-theme='dark'] .app-status-tag--pending { --app-status-tag-color: #efc16a; }
:root[data-theme='dark'] .app-status-tag--info { --app-status-tag-color: #8bbcff; }
:root[data-theme='dark'] .app-status-tag--ready { --app-status-tag-color: #75d3df; }
:root[data-theme='dark'] .app-status-tag--danger { --app-status-tag-color: #ff9baf; }
:root[data-theme='dark'] .app-status-tag--neutral { --app-status-tag-color: #b1bccd; }
:root[data-theme='dark'] .app-status-tag--reversed { --app-status-tag-color: #c2a4ef; }
</style>
