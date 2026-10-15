<script lang="ts">
import { computed, defineComponent, h, nextTick, onBeforeUnmount, onBeforeUpdate, ref, Teleport, useId, watch } from 'vue'
import type { PropType } from 'vue'
import { modalProps, NModal } from 'naive-ui'
import type { ModalProps } from 'naive-ui'
import { useAppMessage } from '../../composables/use-app-message'
import { onDialogPresentationInvalidated, provideDialogPreparation } from '../../composables/use-dialog-presentation'
import type { DialogPresentationPhase } from '../../composables/use-dialog-presentation'
import { getDialogOrigin, releaseDialogOrigin, visibleDialogOrigin, dialogRect, onDialogOriginCaptured } from '../../utils/dialog-origin'
import type { DialogOrigin, DialogRect } from '../../utils/dialog-origin'
import { cloneDialogExitFrame, createDialogMotionController, dialogMotionTiming, dialogOriginFrame, readDialogFrame } from '../../utils/dialog-motion'
import type { DialogExitFrame, DialogMotionFrame } from '../../utils/dialog-motion'

export default defineComponent({
  name: 'AppModal', inheritAttrs: false,
  // 直接继承公开 props，卡片/确认框属性及原有关闭回调不会在迁移时悄悄丢失。
  props: { ...modalProps, originKey: String, origin: Object as PropType<DialogOrigin | null>,
    busy: { type: Boolean, default: false }, ready: { type: Boolean, default: true }, loadError: { type: String, default: '' }, invalidationKey: [String, Number] },
  emits: { 'update:show': (_show: boolean) => true, 'after-enter': () => true, 'before-leave': () => true, 'after-leave': () => true, 'load-error': (_error: string) => true, invalidated: () => true },
  setup(props, { attrs, slots, emit, expose }) {
    const id = useId(), barrier = provideDialogPreparation()
    const phase = ref<DialogPresentationPhase>('idle'), renderedShow = ref(false), motionVisible = ref(false)
    const waitingPosition = ref({ left: '50%', top: '72px' }), waitingTarget = ref<Element | string>('body')
    const pending = computed(() => !props.ready || barrier.pending.value)
    const failure = computed(() => props.loadError || barrier.error.value)
    const motion = createDialogMotionController(), maskMotion = createDialogMotionController()
    let origin: DialogOrigin | null = null, bounds: DialogRect | null = null, exitFrame: DialogExitFrame | null = null
    let generation = 0, disposed = false, nativeClosing = false
    let contentAnimations: Array<{ animation: Animation; element: HTMLElement; willChange: string }> = []
    let sourceBusy: string | null = null, sourceBusySet = false, refreshHeight = ''
    let refreshFrame: DialogExitFrame | null = null, saveFrame: DialogExitFrame | null = null
    let saveFrameBounds: DialogRect | null = null, releaseFrame = 0, retainedMotionFrame = 0
    const refreshing = ref(false), saving = ref(false), refreshTarget = ref<HTMLElement | null>(null)
    // 正常应用始终存在消息提供器；独立 SSR/组件测试没有提供器时仍通过事件报告失败。
    let message: ReturnType<typeof useAppMessage> | undefined
    try { message = useAppMessage() } catch { /* 无消息容器的独立挂载由 load-error 事件接管。 */ }
    const element = (): HTMLElement | null => typeof document === 'undefined' ? null : document.querySelector(`[data-app-modal-id="${id}"]`)
    const mask = (): HTMLElement | null => element()?.closest('.n-modal-container')?.querySelector('.n-modal-mask') ?? null
    const reduced = (): boolean => typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    const viewport = () => ({ width: window.innerWidth, height: window.innerHeight })
    function clearSourceBusy(): void {
      if (!sourceBusySet) return
      if (origin) {
        if (sourceBusy === null) origin.element.removeAttribute('aria-busy')
        else origin.element.setAttribute('aria-busy', sourceBusy)
      }
      sourceBusy = null; sourceBusySet = false
    }
    function stopContent(): void {
      contentAnimations.forEach(({ animation, element, willChange }) => { animation.cancel(); element.style.willChange = willChange })
      contentAnimations = []
    }
    function syncRetainedOpening(frame: DialogExitFrame): void {
      const live = element()
      if (!live) return
      Object.assign(frame.element.style, readDialogFrame(live), { willChange: live.style.willChange })
      Array.from(live.children).forEach((child, index) => {
        const copied = frame.element.children[index]
        if (child instanceof HTMLElement && copied instanceof HTMLElement) {
          copied.style.opacity = getComputedStyle(child).opacity
          copied.style.willChange = child.style.willChange
        }
      })
    }
    function stopRetainedOpening(): void {
      if (retainedMotionFrame) cancelAnimationFrame(retainedMotionFrame)
      retainedMotionFrame = 0
    }
    function continueRetainedOpening(frame: DialogExitFrame): void {
      stopRetainedOpening()
      if (phase.value !== 'opening') return
      // 保存/刷新接住入场中途的画面后，仍沿用原节点的时间轴逐帧展开；不能永久冻结在按钮大小。
      // 原节点继续隐藏，副本只复制视觉值，不持有业务数据或交互状态。
      const tick = (): void => {
        retainedMotionFrame = 0
        if (disposed || !props.show || (frame !== saveFrame && frame !== refreshFrame)) return
        if (phase.value !== 'opening' && phase.value !== 'open') return
        syncRetainedOpening(frame)
        if (phase.value === 'opening') retainedMotionFrame = requestAnimationFrame(tick)
      }
      tick()
    }
    function cleanupFrame(): void { exitFrame?.remove(); exitFrame = null }
    function releaseSaveFrame(): void {
      saveFrame?.remove(); saveFrame = null; saveFrameBounds = null; saving.value = false
      if (!refreshFrame && phase.value !== 'closing') {
        refreshTarget.value = null
        const live = element()
        if (live) { live.style.visibility = 'visible'; live.inert = false; void nextTick(() => focusDialog(live)) }
      }
    }
    function releaseExit(): void { if (phase.value !== 'closing') { cleanupFrame(); releaseSaveFrame() } }
    function reset(immediate = false): void {
      generation++; motion.cancel(); maskMotion.cancel(); stopContent(); stopRetainedOpening(); cleanupFrame(); clearSourceBusy()
      refreshFrame?.remove(); refreshFrame = null; refreshing.value = false; refreshTarget.value = null
      saveFrame?.remove(); saveFrame = null; saveFrameBounds = null; saving.value = false
      if (releaseFrame) cancelAnimationFrame(releaseFrame); releaseFrame = 0
      const previousOrigin = origin
      releaseDialogOrigin(props.originKey, origin); origin = null
      bounds = null; nativeClosing = false; motionVisible.value = false; renderedShow.value = false; phase.value = 'idle'; refreshHeight = ''
      if (!immediate && previousOrigin?.element.isConnected && previousOrigin.element instanceof HTMLElement) {
        // NModal 仍负责焦点栈；显式来源补齐 Safari 鼠标按钮不自动聚焦的情况，子窗会回到父窗入口。
        void nextTick(() => previousOrigin.element instanceof HTMLElement && previousOrigin.element.focus({ preventScroll: true }))
      }
    }
    function notifyShow(show: boolean): void {
      const callback = props.onUpdateShow
      if (Array.isArray(callback)) callback.forEach(handle => handle(show)); else callback?.(show)
      emit('update:show', show)
    }
    function invalidate(): void { reset(true); notifyShow(false); emit('invalidated') }
    const removeInvalidation = onDialogPresentationInvalidated(invalidate)
    watch(() => props.invalidationKey, invalidate, { flush: 'sync' })
    function updateWaitingPosition(): void {
      // 子窗口等待期间不启用自己的焦点锁，取消入口留在父窗口原有的焦点范围内。
      waitingTarget.value = origin?.element.closest('[data-app-modal-id]') ?? 'body'
      const rect = origin ? visibleDialogOrigin(origin, viewport()) : null
      waitingPosition.value = rect ? { left: `${Math.max(12, Math.min(rect.left, window.innerWidth - 250))}px`,
        top: `${Math.max(12, Math.min(rect.top + rect.height + 8, window.innerHeight - 54))}px` } : { left: 'calc(50% - 110px)', top: '72px' }
    }
    function captureExit(): void {
      if (exitFrame || phase.value === 'idle' || phase.value === 'preparing') return
      // 关闭可能发生在两次绘制之间，先补齐当前入场值，再交给回程动画，避免倒退到上一帧。
      const retained = refreshFrame ?? saveFrame
      if (retained && phase.value === 'opening') syncRetainedOpening(retained)
      if (retained) stopRetainedOpening()
      if (refreshFrame) { exitFrame = refreshFrame; refreshFrame = null; refreshing.value = false; refreshTarget.value = null; return }
      if (saveFrame) { exitFrame = saveFrame; bounds = saveFrameBounds; saveFrame = null; saveFrameBounds = null; saving.value = false; refreshTarget.value = null; return }
      const live = element()
      if (!live) return
      if (phase.value === 'open') bounds = dialogRect(live.getBoundingClientRect())
      if (!bounds) return
      exitFrame = cloneDialogExitFrame(live, bounds)
      Object.assign(exitFrame.element.style, readDialogFrame(live))
      // WAAPI 子层的计算透明度不在 cloneNode 中；保留当前正文画面，关闭中途也不会突然变亮。
      Array.from(live.children).forEach((child, index) => {
        const copied = exitFrame?.element.children[index]
        if (child instanceof HTMLElement && copied instanceof HTMLElement) copied.style.opacity = getComputedStyle(child).opacity
      })
      // 捕获与挂载分开，调用方根据关闭、刷新或写入阶段决定何时显示这张不可交互画面。
    }
    function requestShow(show: boolean): void {
      // 业务写入期间连刷新状态条也不能先拆掉画面再让上层拒绝关闭。
      if (!show && props.busy) return
      if (!show) captureExit()
      notifyShow(show)
      // 页面可能因保存中拒绝关闭；不能把未被接受的关闭请求留下的画面盖在真实表单上。
      void nextTick(() => { if (props.show && phase.value !== 'closing') cleanupFrame() })
    }
    function cancelWaiting(): void { const existed = phase.value !== 'idle'; reset(true); notifyShow(false); if (existed) emit('after-leave') }
    function failPreparation(error: string): void {
      if (phase.value !== 'preparing') return
      message?.error(error); emit('load-error', error); cancelWaiting()
    }
    function animateContent(root: HTMLElement, opening: boolean, reduce: boolean, initialOpacities?: string[]): void {
      stopContent()
      if (typeof root.animate !== 'function') return
      for (const [index, child] of Array.from(root.children).entries()) {
        if (!(child instanceof HTMLElement)) continue
        const current = getComputedStyle(child).opacity
        const willChange = child.style.willChange
        // 正文淡入也需独立合成，否则透明度变化会重绘正在缩放的整张表格。
        child.style.willChange = 'opacity'
        const animation = child.animate([{ opacity: opening ? initialOpacities?.[index] ?? 0 : current }, { opacity: opening ? 1 : 0 }], {
          duration: reduce ? 60 : opening ? 200 : 120, delay: opening && !reduce && !initialOpacities ? 90 : 0, fill: 'both', easing: 'ease-out'
        })
        contentAnimations.push({ animation, element: child, willChange })
      }
    }
    function focusDialog(root: HTMLElement): void {
      if (!props.autoFocus || root.contains(document.activeElement)) return
      // Naive 的 active watcher 早于 v-show DOM 更新；预挂载后补一次可见控件聚焦，之后仍由原生焦点栈管理 Tab/Esc。
      const candidates = root.querySelectorAll<HTMLElement>('[autofocus],button:not(:disabled),a[href],input:not(:disabled),textarea:not(:disabled),select:not(:disabled),[tabindex]:not([tabindex="-1"])')
      const target = [...candidates].find(node => node.getClientRects().length && getComputedStyle(node).visibility !== 'hidden' && !node.closest('[inert]'))
      if (target) target.focus({ preventScroll: true })
      else { root.tabIndex = -1; root.focus({ preventScroll: true }) }
    }
    async function enter(from?: DialogMotionFrame, contentFrom?: string[], backdropFrom?: DialogMotionFrame, visibleBounds?: DialogRect): Promise<void> {
      const ticket = ++generation
      // 保持 FocusTrap 的组件结构不变；原生 show 的 false → true 在正式展开时激活焦点栈。
      renderedShow.value = false
      await nextTick()
      if (disposed || ticket !== generation || !props.show) return
      // 同一批 props 先更新 show 后更新 ready 时，等整批更新完成再核对，避免慢请求重开抢跑。
      if (pending.value || failure.value) {
        if (phase.value !== 'preparing') { const nextOrigin = origin; reset(true); void prepare(nextOrigin) }
        else if (failure.value) failPreparation(failure.value)
        return
      }
      // 在本次绘制前解除隐藏，再由原生 autofocus 选中窗口内控件；随后同一微任务设置起始动画帧。
      phase.value = 'opening'; motionVisible.value = true
      const mounted = element()
      if (mounted) { mounted.style.visibility = 'visible'; mounted.inert = false }
      renderedShow.value = true
      await nextTick()
      if (disposed || ticket !== generation || !props.show) return
      const live = element()
      if (!live) { reset(true); return }
      live.style.visibility = 'hidden'; live.style.transform = 'none'; live.style.opacity = '1'
      bounds = dialogRect(live.getBoundingClientRect())
      const reduce = reduced(), source = origin ? visibleDialogOrigin(origin, viewport()) : null
      const radius = getComputedStyle(live).borderRadius
      const initial = from ? { ...from, ...(visibleBounds ? { transform: dialogOriginFrame(bounds, visibleBounds, from.borderRadius, reduce).transform } : {}) } : dialogOriginFrame(bounds, source, origin?.borderRadius ?? radius, reduce)
      const duration = reduce ? dialogMotionTiming.reduced : source ? dialogMotionTiming.enter : dialogMotionTiming.fade
      Object.assign(live.style, initial); live.style.visibility = 'visible'; live.inert = false
      motionVisible.value = true; clearSourceBusy(); cleanupFrame(); focusDialog(live)
      animateContent(live, true, reduce, contentFrom)
      const backdrop = mask()
      if (backdrop) void maskMotion.play(backdrop, backdropFrom ?? { transform: 'none', opacity: '0', borderRadius: '0' }, { transform: 'none', opacity: '1', borderRadius: '0' }, duration)
      if (!await motion.play(live, initial, { transform: 'none', opacity: '1', borderRadius: radius }, duration)
        || disposed || ticket !== generation || !props.show) return
      phase.value = 'open'; stopContent(); live.style.transform = ''; live.style.opacity = ''; live.style.borderRadius = ''
      emit('after-enter')
    }
    async function prepare(explicitOrigin?: DialogOrigin | null): Promise<void> {
      const ticket = ++generation
      origin = explicitOrigin === undefined ? props.origin ?? getDialogOrigin(props.originKey) : explicitOrigin
      if (origin) { sourceBusy = origin.element.getAttribute('aria-busy'); sourceBusySet = true; origin.element.setAttribute('aria-busy', 'true') }
      phase.value = 'preparing'; motionVisible.value = false; renderedShow.value = true
      if (typeof window !== 'undefined') updateWaitingPosition()
      // 首次只借一个不可见更新挂载子组件，绘制前即停用原生 show；等待期间不锁焦点或滚动。
      // trapFocus 必须保持稳定：Naive 的 FocusTrap 切 disabled 会重建整棵插槽并重复请求历史。
      await nextTick()
      if (disposed || ticket !== generation || !props.show) return
      renderedShow.value = false
      await nextTick()
      if (disposed || ticket !== generation || !props.show || phase.value !== 'preparing') return
      if (failure.value) failPreparation(failure.value)
      else if (!pending.value) await enter()
    }
    async function leave(): Promise<void> {
      if (phase.value === 'idle') return
      if (phase.value === 'preparing') { reset(true); emit('after-leave'); return }
      const ticket = ++generation
      captureExit()
      const live = element(), frame = exitFrame?.element
      emit('before-leave')
      phase.value = 'closing'; stopContent()
      if (!live || !frame || !bounds) { reset(); emit('after-leave'); return }
      live.parentElement?.append(frame); exitFrame?.restoreScroll()
      const from = readDialogFrame(frame)
      motion.cancel(); live.inert = true; live.style.visibility = 'hidden'
      const reduce = reduced(), source = origin ? visibleDialogOrigin(origin, viewport()) : null
      const duration = reduce ? dialogMotionTiming.reduced : source ? dialogMotionTiming.leave : dialogMotionTiming.fade
      animateContent(frame, false, reduce)
      const backdrop = mask()
      if (backdrop) void maskMotion.play(backdrop, readDialogFrame(backdrop), { transform: 'none', opacity: '0', borderRadius: '0' }, duration)
      const to = dialogOriginFrame(bounds, source, from.borderRadius, reduce)
      if (!await motion.play(frame, from, to, duration) || disposed || ticket !== generation || props.show) return
      nativeClosing = true; renderedShow.value = false
      // 原生 CSS 过渡已关闭；保留 NModal 的一次更新完成焦点/滚动释放后再卸载内容。
      await nextTick()
      if (ticket !== generation || props.show) return
      reset(); emit('after-leave')
    }
    let stopOrigin = () => undefined as void
    watch(() => props.originKey, key => {
      stopOrigin()
      stopOrigin = onDialogOriginCaptured(key, next => {
        if (phase.value === 'preparing') {
          clearSourceBusy(); origin = props.origin ?? next
          if (origin) { sourceBusy = origin.element.getAttribute('aria-busy'); sourceBusySet = true; origin.element.setAttribute('aria-busy', 'true') }
          updateWaitingPosition()
        } else if (phase.value === 'open' || phase.value === 'opening') {
          // 已打开窗口内显式换单不一定改变 show；新的入口仍须成为回程来源，普通刷新不会登记入口。
          origin = props.origin ?? next
        } else if (phase.value === 'idle' && props.show && !disposed) {
          // 失效时上游忙碌保护可能保留 show；新的显式打开意图仍可重新开始，不能永久卡死。
          void nextTick(() => { if (props.show && phase.value === 'idle' && !disposed) void prepare() })
        }
      })
    }, { immediate: true, flush: 'sync' })
    watch(() => props.origin, next => {
      if (phase.value === 'open' || phase.value === 'opening') { origin = next ?? getDialogOrigin(props.originKey); return }
      if (phase.value !== 'preparing') return
      clearSourceBusy(); origin = next ?? getDialogOrigin(props.originKey)
      if (origin) { sourceBusy = origin.element.getAttribute('aria-busy'); sourceBusySet = true; origin.element.setAttribute('aria-busy', 'true') }
      updateWaitingPosition()
    }, { flush: 'sync' })
    watch(() => props.show, show => {
      if (typeof document === 'undefined') { phase.value = show ? 'preparing' : 'idle'; renderedShow.value = show; return }
      if (show) {
        if (phase.value === 'closing') {
          const latestOrigin = props.origin ?? getDialogOrigin(props.originKey)
          if (pending.value) { reset(true); void prepare(latestOrigin); return }
          if (latestOrigin) origin = latestOrigin
          const from = exitFrame ? readDialogFrame(exitFrame.element) : undefined
          const currentBounds = exitFrame ? dialogRect(exitFrame.element.getBoundingClientRect()) : undefined
          const contentFrom = exitFrame ? Array.from(exitFrame.element.children).map(child => getComputedStyle(child).opacity) : undefined
          const backdrop = mask(), backdropFrom = backdrop ? readDialogFrame(backdrop) : undefined
          // 外壳、正文和遮罩都从当前画面继续，反向时不会先把文字或遮罩重置为透明。
          motion.cancel(); maskMotion.cancel(); stopContent(); void enter(from, contentFrom, backdropFrom, currentBounds)
        } else if (phase.value === 'idle') void prepare()
      } else void leave()
    }, { immediate: true, flush: 'sync' })
    watch(() => props.busy, value => {
      if (releaseFrame) cancelAnimationFrame(releaseFrame)
      if (value && ['open', 'opening'].includes(phase.value) && !saveFrame && !refreshFrame) {
        captureExit(); saveFrame = exitFrame; saveFrameBounds = bounds; exitFrame = null
        const live = element()
        if (live && saveFrame) {
          // 写操作可能先清空草稿再等待列表刷新；整个 busy 期间展示同一张只读画面，避免提前露出空表单。
          live.parentElement?.append(saveFrame.element); saveFrame.restoreScroll()
          saving.value = true; refreshTarget.value = live; refreshHeight = `${bounds?.height ?? live.getBoundingClientRect().height}px`
          live.style.height = refreshHeight; live.style.visibility = 'hidden'; live.inert = false
          continueRetainedOpening(saveFrame)
        }
      } else if (!value && saveFrame && typeof requestAnimationFrame === 'function') {
        // action 的 finally 先解除 busy，调用方 await 随后关闭；留到下次绘制后再释放失败快照。
        releaseFrame = requestAnimationFrame(() => { releaseFrame = requestAnimationFrame(() => {
          releaseFrame = 0
          if (!props.busy && props.show && phase.value !== 'closing') releaseSaveFrame()
        }) })
      }
      // 隐藏真实表单后把键盘焦点停在处理提示上，不能留在已隐藏的提交按钮。
      if (value) void nextTick(() => {
        if (props.busy && props.show) refreshTarget.value?.querySelector<HTMLElement>('.app-modal-waiting[tabindex="0"]')?.focus({ preventScroll: true })
      })
    }, { flush: 'sync' })
    watch(pending, value => {
      if (!value || !['open', 'opening'].includes(phase.value) || refreshFrame) return
      // 同步截取在途请求开始前的画面，父组件随后清空旧单据也不会先露出空白正文。
      captureExit(); refreshFrame = exitFrame; exitFrame = null
      const live = element()
      if (!live || !refreshFrame) return
      live.parentElement?.append(refreshFrame.element); refreshFrame.restoreScroll()
      refreshing.value = true; refreshTarget.value = live; refreshHeight = `${bounds?.height ?? live.getBoundingClientRect().height}px`
      live.style.height = refreshHeight; live.style.visibility = 'hidden'; live.inert = false
      continueRetainedOpening(refreshFrame)
    }, { flush: 'sync' })
    watch([pending, failure, () => props.busy], async () => {
      if (phase.value === 'preparing') {
        await nextTick()
        if (phase.value !== 'preparing' || !props.show) return
        if (failure.value) failPreparation(failure.value)
        else if (!pending.value) void enter()
      } else if (['open', 'opening'].includes(phase.value) && refreshing.value && !pending.value && !failure.value && !props.busy) {
        // 新快照完整到齐才整体替换，窗口高度沿用首次尺寸，较长内容使用原有正文滚动区。
        await nextTick()
        if (!props.show || pending.value || failure.value || props.busy || !refreshFrame) return
        const live = element()
        refreshFrame.remove(); refreshFrame = null; refreshing.value = false; refreshTarget.value = null
        // 新正文必须以完整首帧替换旧画面；从透明再淡入会产生空帧，也会污染紧接着写入时的快照。
        if (live) { if (phase.value !== 'opening') stopContent(); live.style.height = refreshHeight; live.style.visibility = 'visible'; live.inert = false }
      }
    }, { flush: 'post' })
    onBeforeUpdate(() => { if (!props.show && phase.value !== 'idle') captureExit() })
    onBeforeUnmount(() => { disposed = true; stopOrigin(); removeInvalidation(); reset(true) })
    expose({ captureExit, releaseExit, cancelWaiting })
    return () => {
      const preparing = phase.value === 'preparing'
      const forwarded = { ...props } as Record<string, unknown>
      for (const key of ['originKey', 'origin', 'busy', 'ready', 'loadError', 'invalidationKey', 'onAfterEnter', 'onAfterLeave', 'onBeforeLeave', 'onUpdate:show', 'onUpdateShow']) delete forwarded[key]
      const modal = phase.value !== 'idle' ? h(NModal, {
        ...forwarded as ModalProps, ...attrs, show: renderedShow.value, displayDirective: 'show', transformOrigin: 'center',
        class: ['app-modal', attrs.class, !motionVisible.value && 'app-modal--preparing'],
        'data-app-modal-id': id, 'data-dialog-phase': phase.value,
        showMask: props.showMask, trapFocus: props.trapFocus,
        autoFocus: !preparing && props.autoFocus, blockScroll: !preparing && props.blockScroll,
        'onUpdate:show': requestShow,
        onAfterEnter: () => undefined, onBeforeLeave: () => undefined,
        onAfterLeave: () => { if (nativeClosing) cleanupFrame() }
      }, slots) : null
      const waiting = preparing && pending.value && typeof document !== 'undefined' ? h(Teleport, { to: waitingTarget.value }, h('div', {
        class: 'app-modal-waiting', style: waitingPosition.value, role: 'status', 'aria-live': 'polite'
      }, [h('span', '正在准备详情…'), h('button', { type: 'button', onClick: cancelWaiting }, '取消')])) : null
      const refreshStatus = (refreshing.value || saving.value) && refreshTarget.value && typeof document !== 'undefined' ? h(Teleport, { to: refreshTarget.value }, h('div', {
        class: 'app-modal-waiting', style: { visibility: 'visible', right: `${Math.max(16, window.innerWidth - (bounds?.left ?? 0) - (bounds?.width ?? 0))}px`, top: `${Math.max(12, (bounds?.top ?? 0) + 12)}px` },
        role: failure.value ? 'alert' : 'status', tabindex: props.busy ? 0 : undefined
      }, [h('span', props.busy || saving.value ? '正在处理…' : failure.value ? `${failure.value} 请关闭后重试。` : '正在读取新内容…'),
        refreshing.value ? h('button', { type: 'button', disabled: props.busy, onClick: () => requestShow(false) }, failure.value ? '关闭' : '取消等待并关闭') : null])) : null
      return [modal, waiting, refreshStatus]
    }
  }
})
</script>

<style>
/* 只替换 AppModal 的动画；Naive UI 继续负责遮罩、键盘、焦点栈、层级和页面滚动锁。 */
.app-modal { transform-origin: 0 0 !important; }
/* 自动聚焦关闭按钮会启动主题背景过渡；飞行中固定其焦点配色，避免额外的逐帧绘制。 */
.app-modal:is([data-dialog-phase='opening'], [data-dialog-phase='closing']) .n-card-header__close {
  transition: none !important;
}
.app-modal.fade-in-scale-up-transition-enter-active,
.app-modal.fade-in-scale-up-transition-leave-active { transition: none !important; }
.app-modal.fade-in-scale-up-transition-enter-from,
.app-modal.fade-in-scale-up-transition-leave-to,
.app-modal.fade-in-scale-up-transition-enter-to,
.app-modal.fade-in-scale-up-transition-leave-from { transform: none; opacity: 1; }
.n-modal-container:has(.app-modal--preparing) > .n-modal-mask { visibility: hidden !important; pointer-events: none !important; }
.n-modal-container:has(.app-modal--preparing) .n-modal-body-wrapper { pointer-events: none !important; }
.app-modal--preparing { visibility: hidden !important; pointer-events: none !important; }
.n-modal-container:has(.app-modal) > .n-modal-mask { transition: none !important; }
.n-modal-container:has(.app-modal) > .n-modal-mask.fade-in-transition-enter-from,
.n-modal-container:has(.app-modal) > .n-modal-mask.fade-in-transition-leave-to { opacity: 1; }
.app-modal-waiting { position: fixed; z-index: 10000; display: flex; align-items: center; gap: 16px; padding: 10px 14px;
  border: 1px solid var(--workspace-field-border); border-radius: 12px; background: var(--app-modal-surface);
  color: var(--workspace-field-text, var(--app-text)); box-shadow: 0 8px 24px #0002; font-size: 13px; }
.app-modal-waiting button { border: 0; background: transparent; color: var(--workspace-field-accent); cursor: pointer; font: inherit; padding: 4px; }
.app-modal-waiting button:focus-visible { outline: 2px solid currentColor; outline-offset: 2px; }
[data-dialog-exit-frame] { pointer-events: none !important; user-select: none !important; }
</style>
