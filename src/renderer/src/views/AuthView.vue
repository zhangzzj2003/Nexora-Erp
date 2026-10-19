<script setup lang="ts">
// 公共界面文案随语言偏好即时更新，不影响输入草稿。
import { useSettingsStore } from '../store/settings-store'
const { t } = useSettingsStore()

// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../components/app/AppButton.vue'
import { useAppStore } from '../store/app-store'
import { nexoraLogo } from '../assets/brand'
import IconArrowRightLine from '~icons/ri/arrow-right-line'
import IconServerLine from '~icons/ri/server-line'

// 管理员初始化和正常登录共用凭据表单，提交分支由当前阶段判断。
const {
  screen,
  server,
  username,
  password,
  busy,
  connectionLost,
  authenticate,
  switchServer
} = useAppStore()
</script>

<template>
  <!-- 桌面左右分栏呈现品牌与登录入口，窄窗口再合为单列，始终共用一份表单。 -->
  <section class="auth-stage" aria-labelledby="auth-brand-title">
    <div class="auth-intro">
      <header class="auth-brand">
        <span class="auth-brand-mark" aria-hidden="true"><img :src="nexoraLogo" alt="" /></span>
        <div>
          <p class="eyebrow">NEXORA WORKSPACE</p>
          <h1 id="auth-brand-title">{{ t('开始使用联光 ERP') }}</h1>
        </div>
      </header>
      <div class="auth-intro-copy">
        <h2>{{ t('从采购到交付，') }}<br /><span>{{ t('每一步清晰有序。') }}</span></h2>
        <p>{{ t('连接采购、库存、生产与销售，在同一个工作台协同处理日常业务。') }}</p>
      </div>
      <!-- 业务范围以辅助文字呈现，避免被误认为登录前可点击的业务入口。 -->
      <ul class="auth-domains" :aria-label="t('业务协同')">
        <li>{{ t('采购') }}</li>
        <li>{{ t('库存') }}</li>
        <li>{{ t('生产') }}</li>
        <li>{{ t('销售') }}</li>
      </ul>
    </div>
    <section class="auth-card" aria-labelledby="auth-form-title">
      <p class="eyebrow">{{ screen === 'setup' ? t('首次使用') : t('欢迎回来') }}</p>
      <h2 id="auth-form-title">{{ screen === 'setup' ? t('创建首位管理员') : t('登录工作台') }}</h2>
      <p class="auth-description">
        {{
          screen === 'setup'
            ? t('管理员可以创建用户并分配角色。请设置至少 12 位的密码。')
            : t('使用 {server} 的账号，继续处理日常业务。', { server: server?.name || t('当前服务端') })
        }}
      </p>
      <!-- 继续使用公共输入和按钮，原生校验、密码显隐及提交路径保持一致。 -->
      <form @submit.prevent="authenticate">
        <label
          >{{ t("用户名") }}<AppInput
            v-model.trim="username"
            autocomplete="username"
            minlength="3"
            maxlength="40"
            required
            :placeholder="t('例如 admin')"
        /></label>
        <label
          >{{ t("密码") }}<AppInput
            v-model="password"
            type="password"
            :autocomplete="screen === 'setup' ? 'new-password' : 'current-password'"
            :minlength="screen === 'setup' ? 12 : undefined"
            required
            :placeholder="t('输入密码')"
        /></label>
        <AppButton type="submit" :disabled="busy || connectionLost" :loading="busy" variant="primary" size="large" class="auth-submit">
          {{ busy ? t('请稍候…') : screen === 'setup' ? t('创建管理员') : t('登录') }}
          <IconArrowRightLine v-if="!busy" class="auth-submit-arrow" aria-hidden="true" />
        </AppButton>
      </form>
      <div class="auth-card-footer">
        <AppButton type="button" @click="switchServer" class="auth-switch" variant="text">
          <IconServerLine aria-hidden="true" />{{ t('切换服务端') }}
        </AppButton>
      </div>
    </section>
  </section>
</template>

<style scoped>
/* 登录页只维护自身排版，颜色沿用公共变量，兼容用户选择的各组主题色。 */
.auth-stage {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 440px);
  align-items: stretch;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--workspace-field-border) 75%, transparent);
  border-radius: 22px;
  background: var(--workspace-field-background);
  box-shadow: 0 24px 70px -28px color-mix(in srgb, var(--workspace-field-text) 24%, transparent);
}
/* 左侧只承担品牌识别；边框、圆角和阴影统一归外层面板，消除两块悬浮卡片感。 */
.auth-intro { min-width: 0; display: flex; flex-direction: column; padding: 44px 44px 28px; border-right: 1px solid color-mix(in srgb, var(--workspace-field-border) 60%, transparent); background: color-mix(in srgb, var(--app-accent-tint) 58%, var(--workspace-field-background)); }
.auth-brand { display: flex; align-items: center; gap: 12px; }
.auth-brand-mark { display: grid; place-items: center; flex: none; width: 44px; height: 44px; border-radius: 12px; background: #fff; }
.auth-brand-mark img { display: block; width: 40px; height: 40px; object-fit: contain; }
.auth-brand .eyebrow { font-size: 9px; letter-spacing: .19em; }
.auth-brand h1 { margin: 7px 0 0; color: var(--workspace-field-text); font-size: 18px; font-weight: 650; line-height: 1.3; letter-spacing: -.035em; }
.auth-intro-copy { margin-block: auto; padding-block: 48px; }
.auth-intro-copy h2 { margin: 0; color: var(--workspace-field-text); font-size: 30px; font-weight: 650; line-height: 1.55; letter-spacing: -.045em; }
.auth-intro-copy p { max-width: 340px; margin: 20px 0 0; color: var(--workspace-field-muted); font-size: 13px; line-height: 1.9; }
.auth-domains { display: flex; flex-wrap: wrap; gap: 12px; margin: 0; padding: 0; list-style: none; color: var(--workspace-field-muted); font-size: 11px; }
.auth-domains li + li { border-left: 1px solid color-mix(in srgb, var(--workspace-field-border) 85%, transparent); padding-left: 12px; }
.auth-card {
  --app-field-height: 46px;
  --app-field-font-size: 14px;
  min-width: 0;
  padding: 44px 40px 0;
  color: var(--workspace-field-text);
}
.auth-card > .eyebrow { display: flex; align-items: center; gap: 7px; font-size: 11px; font-weight: 600; letter-spacing: .08em; }
.auth-card > .eyebrow::before { content: ''; width: 16px; height: 2px; border-radius: 2px; background: currentColor; }
.auth-card h2 { margin: 13px 0 0; font-size: 28px; font-weight: 650; line-height: 1.35; letter-spacing: -.04em; }
.auth-description { margin: 12px 0 0; color: var(--workspace-field-muted); font-size: 13px; line-height: 1.8; overflow-wrap: anywhere; }
.auth-card form { display: grid; gap: 20px; margin-top: 28px; }
.auth-card label { gap: 9px; color: var(--workspace-field-text); font-size: 12px; font-weight: 600; }
.auth-submit { width: 100%; margin-top: 4px; }
.auth-submit-arrow { width: 17px; height: 17px; margin-left: 10px; }
.auth-card-footer { display: flex; justify-content: center; margin-top: 28px; padding: 19px 0 21px; border-top: 1px solid color-mix(in srgb, var(--workspace-field-border) 60%, transparent); }
.auth-switch { min-height: 24px; font-size: 12px; }
.auth-switch svg { width: 15px; height: 15px; margin-right: 7px; }
/* 单列时收起介绍，品牌保持紧邻表单，避免矮窗口需要越过大块说明才能登录。 */
@media (max-width: 860px) {
  .auth-stage { grid-template-columns: minmax(0, 1fr); max-width: 440px; }
  .auth-intro { padding: 24px 32px; border-right: 0; border-bottom: 1px solid color-mix(in srgb, var(--workspace-field-border) 60%, transparent); }
  .auth-intro-copy, .auth-domains { display: none; }
  .auth-card { padding: 32px 32px 0; }
}
/* 窄屏减少内边距；英文长标题和服务端名称换行，不扩大卡片宽度。 */
@media (max-width: 480px) {
  .auth-stage { border-radius: 18px; }
  .auth-intro { padding: 22px 24px; }
  .auth-brand { gap: 10px; }
  .auth-brand h1 { font-size: 17px; }
  .auth-brand-mark { width: 44px; height: 44px; border-radius: 12px; }
  .auth-brand-mark img { width: 40px; height: 40px; }
  .auth-card { padding: 28px 24px 0; }
  .auth-card h2 { font-size: 25px; }
}
</style>
