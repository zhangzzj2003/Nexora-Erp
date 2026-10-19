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
import IconShoppingBagLine from '~icons/ri/shopping-bag-line'
import IconArchiveStackLine from '~icons/ri/archive-stack-line'
import IconSettings3Line from '~icons/ri/settings-3-line'
import IconTruckLine from '~icons/ri/truck-line'

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
      <!-- 流程仅作业务范围示意，不使用虚构统计，也不作为登录前的业务入口。 -->
      <ul class="auth-workflow" :aria-label="t('业务协同')">
        <li><span><IconShoppingBagLine aria-hidden="true" /></span>{{ t('采购') }}</li>
        <li><span><IconArchiveStackLine aria-hidden="true" /></span>{{ t('库存') }}</li>
        <li><span><IconSettings3Line aria-hidden="true" /></span>{{ t('生产') }}</li>
        <li><span><IconTruckLine aria-hidden="true" /></span>{{ t('销售') }}</li>
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
/* 登录页只维护自身排版，颜色沿用公共变量，兼容用户的六组主题色。 */
.auth-stage { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 440px); align-items: center; gap: clamp(40px, 6vw, 96px); }
.auth-intro { min-width: 0; padding-block: 24px; }
.auth-brand { display: flex; align-items: center; gap: 13px; }
.auth-brand-mark { display: grid; place-items: center; flex: none; width: 52px; height: 52px; border-radius: 14px; background: #fff; box-shadow: 0 3px 12px #152b4810; }
.auth-brand-mark img { display: block; width: 48px; height: 48px; object-fit: contain; }
.auth-brand .eyebrow { font-size: 9px; letter-spacing: .19em; }
.auth-brand h1 { margin: 7px 0 0; color: var(--workspace-field-text); font-size: 22px; font-weight: 650; line-height: 1.3; letter-spacing: -.035em; }
.auth-intro-copy { margin-top: 42px; }
.auth-intro-copy h2 { margin: 0; color: var(--workspace-field-text); font-size: clamp(28px, 2.8vw, 38px); font-weight: 650; line-height: 1.55; letter-spacing: -.045em; }
.auth-intro-copy h2 span { color: var(--workspace-field-accent); }
.auth-intro-copy p { max-width: 360px; margin: 20px 0 0; color: var(--workspace-field-muted); font-size: 14px; line-height: 1.9; }
.auth-workflow { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 20px; max-width: 380px; margin: 40px 0 0; padding: 0; list-style: none; }
.auth-workflow li { position: relative; display: flex; flex-direction: column; align-items: center; gap: 12px; color: var(--workspace-field-muted); font-size: 12px; text-align: center; }
.auth-workflow li + li::before { content: ''; position: absolute; top: 26px; right: calc(50% + 33px); width: calc(100% - 46px); height: 1px; background: color-mix(in srgb, var(--workspace-field-accent) 24%, transparent); }
.auth-workflow li > span { display: grid; place-items: center; width: 52px; height: 52px; border: 1px solid color-mix(in srgb, var(--workspace-field-accent) 15%, transparent); border-radius: 15px; background: var(--workspace-field-background); color: var(--workspace-field-accent); }
.auth-workflow svg { width: 23px; height: 23px; }
.auth-card {
  --app-field-height: 46px;
  --app-field-font-size: 14px;
  padding: 34px 36px 0;
  border: 1px solid color-mix(in srgb, var(--workspace-field-border) 75%, transparent);
  border-radius: 22px;
  background: var(--workspace-field-background);
  color: var(--workspace-field-text);
  box-shadow: 0 20px 60px -24px color-mix(in srgb, var(--workspace-field-text) 20%, transparent), 0 2px 8px #152b4804;
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
  .auth-stage { grid-template-columns: minmax(0, 440px); justify-content: center; gap: 28px; }
  .auth-intro { padding: 0; }
  .auth-brand { justify-content: center; }
  .auth-intro-copy, .auth-workflow { display: none; }
}
/* 窄屏减少内边距；英文长标题和服务端名称换行，不扩大卡片宽度。 */
@media (max-width: 480px) {
  .auth-stage { gap: 24px; }
  .auth-brand { gap: 10px; }
  .auth-brand h1 { font-size: 19px; }
  .auth-brand-mark { width: 44px; height: 44px; border-radius: 12px; }
  .auth-brand-mark img { width: 40px; height: 40px; }
  .auth-card { padding: 28px 24px 0; border-radius: 18px; }
  .auth-card h2 { font-size: 25px; }
}
</style>
