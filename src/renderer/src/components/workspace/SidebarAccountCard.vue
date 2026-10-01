<script setup lang="ts">
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../app/AppButton.vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useAppStore } from '../../store/app-store'
import IconUser3Line from '~icons/ri/user-3-line'
import IconLogoutBoxRLine from '~icons/ri/logout-box-r-line'
import { accountRoleText } from '../../utils/account-role'

const { user, roles, busy, logout } = useAppStore()
const card = ref<HTMLElement | null>(null)
const menuOpen = ref(false)

const roleText = computed(() => accountRoleText(user.value?.roles ?? [], roles.value))

function closeWhenFocusLeaves(event: FocusEvent): void {
  if (!(event.relatedTarget instanceof Node) || !card.value?.contains(event.relatedTarget))
    menuOpen.value = false
}

function closeWhenClickOutside(event: PointerEvent): void {
  // 点击卡片外关闭菜单；账号按钮本身负责切换，避免悬停时意外弹出退出操作。
  if (event.target instanceof Node && !card.value?.contains(event.target)) menuOpen.value = false
}

function closeOnEscape(): void {
  menuOpen.value = false
  // 释放焦点，避免关闭后按钮仍保留菜单操作的视觉焦点。
  if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
}

onMounted(() => document.addEventListener('pointerdown', closeWhenClickOutside))
onBeforeUnmount(() => document.removeEventListener('pointerdown', closeWhenClickOutside))
</script>

<template>
  <div
    v-if="user"
    ref="card"
    class="sidebar-account"
    @focusout="closeWhenFocusLeaves"
    @keydown.esc.stop="closeOnEscape"
  >
    <div class="sidebar-account-row">
      <AppButton
        type="button"
        :aria-expanded="menuOpen"
        aria-controls="sidebar-account-menu"
        @click="menuOpen = !menuOpen"
        class="sidebar-account-card"
        variant="plain"
      >
        <span class="sidebar-account-avatar" aria-hidden="true"><IconUser3Line /></span>
        <span class="sidebar-account-identity">
          <strong :title="user.username">{{ user.username }}</strong>
          <small :title="roleText">{{ roleText }}</small>
        </span>
      </AppButton>
      <!-- 主题入口已统一放在顶部，账号卡片只保留身份和退出菜单。 -->
    </div>
    <Transition name="account-menu">
      <div v-if="menuOpen" id="sidebar-account-menu" class="sidebar-account-menu">
        <AppButton type="button" :disabled="busy" @click="logout" variant="plain">
          <IconLogoutBoxRLine aria-hidden="true" />退出登录
        </AppButton>
      </div>
    </Transition>
  </div>
</template>
