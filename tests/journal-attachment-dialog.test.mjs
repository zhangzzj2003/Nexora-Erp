import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp, h } from 'vue'
import { createPinia } from 'pinia'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

// 保留附件组件的真实响应式生命周期，只把文件选择与服务端接口替换成可控的等待。
const source = `import {defineStore} from 'pinia';import {ref} from 'vue';
export const reads=[],writes=[];
export const usePiniaAppStore=defineStore('journal-attachment-dialog',()=>{
 const user=ref({id:1,roles:['finance','viewer'],permissions:['journal.view','journal.attachment']});
 return {user,server:ref({id:'instance',fingerprint:'first'}),connectionLost:ref(false),
 can:permission=>user.value?.permissions.includes(permission)??false,
 loadJournalAttachments:id=>new Promise((resolve,reject)=>reads.push({id,resolve,reject})),
 uploadJournalAttachment:id=>new Promise(resolve=>writes.push({kind:'upload',id,resolve})),
 reverseJournalAttachment:async(id,attachmentId)=>{writes.push({kind:'reverse',id,attachmentId})},
 saveJournalAttachment:async()=>null};
});`
const attachment = { id: 9, journal_id: 7, file_name: '凭据.pdf', reversal: null, can_reverse: true }
async function fixture(t) {
  const server = await createServer({ configFile: false, plugins: [{
    name: 'journal-attachment-dialog-fixture', enforce: 'pre',
    resolveId(id, importer) {
      if (!importer?.includes('/src/renderer/')) return
      if (id.endsWith('/store/app-store')) return '\0attachment-store'
      if (id.endsWith('.vue') && !id.endsWith('/JournalAttachments.vue')) return '\0attachment-empty'
    },
    load(id) {
      if (id === '\0attachment-store') return source
      if (id === '\0attachment-empty') return 'export default {render:()=>null}'
    }
  }, vue()], optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  t.after(() => server.close())
  const { usePiniaAppStore, reads, writes } = await server.ssrLoadModule('\0attachment-store')
  const { default: View } = await server.ssrLoadModule('/src/renderer/src/views/workspace/finance/JournalAttachments.vue')
  const { provideDialogPreparation } = await server.ssrLoadModule('/src/renderer/src/composables/use-dialog-presentation.ts')
  const pinia = createPinia(), store = usePiniaAppStore(pinia)
  async function exercise(action) {
    let barrier, failure
    const Wrapped = { ...View, ssrRender: undefined, render: () => null, async setup(props, context) {
      const page = View.setup(props, context)
      try { await action(page, barrier) } catch (cause) { failure = cause }
      return page
    } }
    const Root = { setup() {
      barrier = provideDialogPreparation()
      return () => h(Wrapped, { journalId: 7 })
    } }
    await renderToString(createSSRApp(Root).use(pinia))
    if (failure) throw failure
  }
  return { store, reads, writes, exercise }
}

test('凭证附件首屏阻止提前展开，刷新失败保留正文但旧权限不能上传或撤销', async t => {
  const { store, reads, writes, exercise } = await fixture(t)
  await exercise(async (page, barrier) => {
    assert.equal(barrier.pending.value, true)
    const initial = page.reload()
    // 相同授权集合重排不会重读附件，也不会把首屏屏障错误地切换到新代次。
    store.user = { ...store.user, roles: [...store.user.roles].reverse(), permissions: [...store.user.permissions].reverse() }
    assert.equal(reads.length, 1)
    reads[0].resolve({ items: [attachment], can_modify: true })
    await initial
    assert.equal(barrier.pending.value, false)
    assert.equal(page.canModify.value, true)
    page.reason.value = '上传依据'
    page.reverseId.value = 9
    page.reverseReason.value = '撤销依据'
    const refreshing = page.reload()
    assert.equal(barrier.pending.value, true)
    assert.equal(page.rows.value[0].id, 9)
    await page.upload()
    await page.reverse()
    assert.equal(writes.length, 0)
    reads[1].reject(new Error('附件读取失败'))
    await refreshing
    assert.match(barrier.error.value, /附件读取失败/)
    assert.equal(page.rows.value[0].id, 9)
    assert.equal(page.canModify.value, false)
    await page.upload()
    await page.reverse()
    assert.equal(writes.length, 0)
  })
})

test('附件会话失效取消旧读取和写入回填，不能解除新请求的屏障', async t => {
  const { store, reads, writes, exercise } = await fixture(t)
  await exercise(async page => {
    const oldRead = page.reload()
    store.server = { ...store.server, fingerprint: 'second' }
    assert.equal(reads.length, 2)
    reads[0].resolve({ items: [attachment], can_modify: true })
    await oldRead
    assert.equal(page.loading.value, true)
    assert.deepEqual(page.rows.value, [])
    reads[1].resolve({ items: [attachment], can_modify: true })
    await new Promise(resolve => setImmediate(resolve))
    page.reason.value = '票据来源'
    const upload = page.upload()
    assert.equal(writes.length, 1)
    store.user = { ...store.user, permissions: [] }
    writes[0].resolve(attachment)
    await upload
    assert.deepEqual(page.rows.value, [])
    assert.equal(page.message.value, '')
    assert.equal(page.canModify.value, false)
    assert.equal(reads.length, 2, '迟到写入不能为已经失效的凭证再发起读取')
  })
})
