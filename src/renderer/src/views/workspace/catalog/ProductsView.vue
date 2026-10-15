<script setup lang="ts">
import { computed, ref, watch, onUnmounted } from 'vue'
import { NCollapse } from 'naive-ui'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import { storeToRefs } from 'pinia'
import { useRoute } from 'vue-router'
import { usePiniaAppStore } from '../../../store/app-store'
import { productKindLabels, productKinds } from '../../../../../shared/product-api'
import type { ProductProfile } from '../../../../../shared/product-api'
import type { Bom } from '../../../../../shared/erp-api'
import { materialChoiceFacts } from '../../../utils/material-selection'
import { captureDialogOrigin } from '../../../utils/dialog-origin'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import WorkspacePagination from '../../../components/workspace/WorkspacePagination.vue'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import AppInput from '../../../components/app/AppInput.vue'
import AppButton from '../../../components/app/AppButton.vue'
import ProductEditor from './ProductEditor.vue'
import ProductModelsDialog from './ProductModelsDialog.vue'
import BomEditor from './BomEditor.vue'
import BomDetailDialog from './BomDetailDialog.vue'
// 页面只组织展示，分页、草稿、版本写入和会话边界统一放在 Pinia。
const store = usePiniaAppStore(), route = useRoute()
const {productQuery: query, productResult: result, productModels: models, productsLoading, productsError,
  productDetailRecord: detail, productDetailId, productDetailLoading, productDetailError,
  productBomRecords, productChangeRecords, productEditorOpen, bomDetailRecord, bomDetailLoading, bomDetailError,
  materialCategories, busy, connectionLost} = storeToRefs(store)
const modelsOpen = ref(false), bomOpen = ref(false), detailsOpen = ref(false)
const seriesName = computed(() => models.value.find(row => row.id === query.value.model_id)?.name ?? '全部产品')
const bomColumns = [{key:'version',title:'BOM 版本',width:'110'}, {key:'status',title:'状态',width:'90'},
  {key:'source',title:'派生来源'}, {key:'actions',title:'操作',width:'300'}]
const facts = computed(() => detail.value ? materialChoiceFacts(detail.value.material, materialCategories.value) : [])
const technicalFacts = computed(() => detail.value ? materialChoiceFacts(detail.value.material, materialCategories.value, true) : [])
const showDetail = computed(() => detailsOpen.value && !!productDetailId.value && !bomOpen.value && !productEditorOpen.value
  && !bomDetailRecord.value && !bomDetailLoading.value && !bomDetailError.value)
watch(() => JSON.stringify([query.value.query, query.value.kind, query.value.model_id,
  store.user?.id, store.user?.permissions.slice().sort(), connectionLost.value, store.server?.id, store.server?.fingerprint]),
  () => {if (store.can('inventory.view') && !connectionLost.value) void store.queryProducts()}, {immediate:true})
// 固定编号的外部定位只消费一次；后续系列筛选和分页使用当前服务端结果。
let consumedRoute = ''
watch([result, () => route.query.product_id], ([page, rawId]) => {
  if (!page) {store.closeProduct(); detailsOpen.value = false; return}
  const routeId = Number(rawId)
  if (Number.isSafeInteger(routeId) && routeId > 0 && consumedRoute !== String(rawId)) {
    consumedRoute = String(rawId); void store.openProduct(routeId); return
  }
  // 切换筛选时撤销旧读取，迟到的上一系列响应不能回填右侧。
  const selected = page.items.find(row => row.id === productDetailId.value) ?? page.items[0]
  if (selected && selected.id !== productDetailId.value) void store.openProduct(selected.id)
  else if (!selected) store.closeProduct()
}, {immediate:true})
onUnmounted(() => {store.closeProduct(); store.closeBomDetail()})
function pageChange(page: number, size: number): void {
  if (busy.value || connectionLost.value) return
  // 翻页开始即撤销原产品选择，避免新页在途时继续操作上一页 BOM。
  detailsOpen.value = false; store.closeProduct()
  query.value.page_size = size; void store.queryProducts(page)
}
function reset(): void {
  if (busy.value || connectionLost.value) return
  const unchanged = !query.value.query && query.value.kind === null
  query.value = {...query.value,query:'',kind:null,page:1}
  // 没有搜索条件变化时，筛选监听不会触发；仍须真正查询第一页。
  if (unchanged) {store.closeProduct(); void store.queryProducts(1)}
}
function selectSeries(id: number | null): void {
  if (busy.value || connectionLost.value || query.value.model_id === id) return
  detailsOpen.value = false; store.closeProduct()
  query.value = {...query.value,model_id:id,query:'',kind:null,page:1}
}
function selectProduct(id: number): Promise<void> {
  detailsOpen.value = false
  return store.openProduct(id)
}
function startBom(source?: Bom): void {
  if (detail.value && store.prepareProductBom(detail.value.material_id, source)) bomOpen.value = true
}
async function afterBomSaved(): Promise<void> {
  // 写后只刷新当前产品范围，不能把另一个产品的 BOM 显示在此详情中。
  if (productDetailId.value) await store.openProduct(productDetailId.value)
}
function changeSummary(value: ProductProfile): string {
  return [value.material.sku, value.material.name, productKindLabels[value.kind], value.model_name || '未归组',
    value.configuration_name || '未设置配置', value.material.specification || '未填写规格', value.material.unit].join(' · ')
}
function sameModel(): void {
  if (!detail.value?.model_id) return
  detailsOpen.value = false; selectSeries(detail.value.model_id)
}
</script>
<template>
  <section class="product-workspace">
    <aside class="product-series" aria-label="产品系列">
      <div class="series-heading"><h3>产品系列</h3><span class="muted">按系列浏览产品与 BOM</span></div>
      <nav class="series-list" aria-label="选择产品系列">
        <AppButton variant="plain" class="series-item" :class="{'is-active':query.model_id === null}" :aria-pressed="query.model_id === null" :disabled="busy || connectionLost" @click="selectSeries(null)">
          <strong>全部产品</strong><small>全部系列及未归组产品</small>
        </AppButton>
        <AppButton v-for="model in models" :key="model.id" variant="plain" class="series-item" :class="{'is-active':query.model_id === model.id}" :aria-pressed="query.model_id === model.id" :disabled="busy || connectionLost" @click="selectSeries(model.id)">
          <strong>{{ model.name }}</strong><small>{{ model.code }}</small>
        </AppButton>
      </nav>
      <p v-if="!models.length && !productsLoading" class="series-empty muted">尚无产品系列，未归组的产品可在全部产品中查看。</p>
      <AppButton v-if="store.can('catalog.manage')" class="series-manage" :disabled="busy || connectionLost" @click="modelsOpen = true">管理产品系列</AppButton>
    </aside>
    <div class="product-main">
    <header class="product-series-title"><div><span class="muted">当前系列</span><h3>{{ seriesName }}</h3></div>
      <div v-if="store.can('catalog.manage')" class="product-toolbar">
        <AppButton :disabled="busy || connectionLost" @click="store.startProduct('existing')">纳入已有物料</AppButton>
        <AppButton variant="primary" :disabled="busy || connectionLost" @click="store.startProduct('new')">新增产品</AppButton>
      </div>
    </header>
    <section class="product-picker" aria-label="系列产品">
      <div class="product-filters">
        <label>搜索产品<AppInput v-model.trim="query.query" maxlength="120" placeholder="编码、名称、规格或配置" /></label>
        <label>产品类型<WorkspaceSelect v-model="query.kind" :options="[{value:null,label:'全部类型'},...productKinds.map(value=>({value,label:productKindLabels[value]}))]" /></label>
        <AppButton :disabled="busy || connectionLost" @click="reset">重置</AppButton>
        <AppButton :disabled="productsLoading || connectionLost" @click="store.queryProducts()">查询</AppButton>
      </div>
      <p v-if="productsLoading" class="muted" role="status">正在读取产品…</p>
      <p v-else-if="productsError" class="product-query-error" role="alert">{{ productsError }}，请重试查询。</p>
      <div v-else-if="result?.items.length" class="product-options" role="group" aria-label="选择产品查看 BOM">
        <AppButton v-for="row in result.items" :key="row.id" variant="plain" class="product-option" :class="{'is-active':productDetailId === row.id}" :aria-pressed="productDetailId === row.id" :disabled="busy || connectionLost" @click="selectProduct(row.id)">
          <strong>{{ row.material.name }}</strong><span>{{ row.configuration_name || '未设置配置' }} · {{ row.material.sku }}</span>
        </AppButton>
      </div>
      <p v-else class="muted">{{ store.can('catalog.manage') ? '暂无匹配产品，可新建产品或纳入已有物料。' : '暂无匹配产品，请调整搜索条件。' }}</p>
      <WorkspacePagination :page="result?.page ?? query.page" :page-size="query.page_size" :total="result?.total ?? 0" :disabled="productsLoading || connectionLost || busy" @change="pageChange" />
    </section>
    <section v-if="productDetailId" class="product-bom-panel" aria-label="选中产品的 BOM">
      <header v-if="detail" class="product-bom-heading">
        <div><span class="muted">{{ detail.material.sku }} · {{ detail.configuration_name || '未设置配置' }}</span><h3>{{ detail.material.name }}</h3><p class="muted">{{ detail.material.spec_summary || detail.material.specification || '未填写规格' }}</p></div>
        <div class="product-toolbar">
          <AppButton :disabled="busy || connectionLost" @click.capture="captureDialogOrigin('product-detail',$event)" @click="detailsOpen = true">产品资料</AppButton>
          <AppButton v-if="store.can('catalog.manage')" :disabled="busy || connectionLost" @click="store.startProduct('edit',detail.id)">编辑产品</AppButton>
          <AppButton v-if="store.can('bom.create')" variant="primary" :disabled="busy || connectionLost" @click="startBom()">新建 BOM</AppButton>
        </div>
      </header>
        <WorkspaceTable v-if="store.can('production.view')" title="关联 BOM" :loading="productDetailLoading" :error="productDetailError" :data="productBomRecords" :columns="bomColumns" :min-table-width="680">
          <template #cell-version="{row}">#{{ row.id }} · V{{ row.version }}</template>
          <template #cell-status="{row}">{{ {draft:'草稿',active:'已启用',retired:'已停用',cancelled:'已取消'}[row.status] }}</template>
          <template #cell-source="{row}"><AppButton v-if="row.source_bom" size="small" :disabled="busy || connectionLost" @click="store.openBomDetail(row.source_bom.id)">{{ row.source_bom.product_name }} · V{{ row.source_bom.version }}</AppButton><span v-else>独立创建</span></template>
          <template #cell-actions="{row}"><div class="form-actions">
            <AppButton size="small" :disabled="busy || connectionLost" @click="store.openBomDetail(row.id)">BOM 详情</AppButton>
            <AppButton v-if="row.status !== 'cancelled' && store.can('bom.create')" size="small" :disabled="busy || connectionLost" @click="startBom(row)">复制派生</AppButton>
            <AppButton v-if="row.status === 'draft' && store.can('bom.activate')" size="small" :disabled="busy || connectionLost || productBomRecords.some(item=>item.status==='active')" @click="store.activateBom(row.id).then(afterBomSaved)">启用</AppButton>
            <AppButton v-if="row.status === 'active' && store.can('bom.retire')" size="small" :disabled="busy || connectionLost" @click="store.retireBom(row.id).then(afterBomSaved)">停用</AppButton>
            <AppButton v-if="row.status === 'draft' && store.can('bom.cancel')" size="small" :disabled="busy || connectionLost" @click="store.cancelBom(row.id).then(afterBomSaved)">取消草稿</AppButton>
          </div></template>
          <template #empty>此产品尚未建立 BOM。</template>
        </WorkspaceTable>
        <p v-else class="muted">当前账号没有生产查看权限，关联 BOM 内容不加载。</p>
    </section>
    </div>
    <ProductEditor v-if="!bomOpen && productEditorOpen" />
    <ProductModelsDialog v-model:show="modelsOpen" />
    <BomEditor v-model:show="bomOpen" @saved="afterBomSaved" />
    <BomDetailDialog />
    <WorkspaceDocumentDialog origin-key="product-detail" :show="showDetail" read-only title="产品详情" :data="[]" :columns="[]" :show-lines="false"
      :ready="!productDetailLoading" :load-error="productDetailError" :busy="busy" @update:show="detailsOpen = $event" @invalidated="detailsOpen = false">
      <template #basicInfo><template v-if="detail">
        <div class="document-detail-field"><span>产品编码</span><strong>{{ detail.material.sku }}</strong></div>
        <div class="document-detail-field"><span>产品名称</span><strong>{{ detail.material.name }}</strong></div>
        <div class="document-detail-field"><span>产品类型</span><strong>{{ productKindLabels[detail.kind] }}</strong></div>
        <div class="document-detail-field"><span>产品系列</span><strong>{{ detail.model_name || '未归组' }}</strong></div>
        <div class="document-detail-field"><span>配置</span><strong>{{ detail.configuration_name || '—' }}</strong></div>
        <div v-for="fact in facts" :key="fact.key" class="document-detail-field"><span>{{ fact.label }}</span><strong>{{ fact.value }}</strong></div>
      </template></template>
      <template #afterLines><template v-if="detail">
        <NCollapse v-if="technicalFacts.length" class="product-more"><AppCollapseItem name="specifications" title="规格与更多资料">
          <dl><div v-for="fact in technicalFacts" :key="fact.key"><dt>{{ fact.label }}</dt><dd>{{ fact.value }}</dd></div></dl>
        </AppCollapseItem></NCollapse>
        <div class="form-actions product-section-actions">
          <AppButton v-if="store.can('catalog.manage')" :disabled="busy || connectionLost" @click="store.startProduct('edit',detail.id)">编辑产品</AppButton>
          <AppButton v-if="detail.model_id" :disabled="busy" @click="sameModel">查看同系列产品</AppButton>
          <AppButton v-if="store.can('bom.create')" :disabled="busy || connectionLost" @click="startBom()">新建 BOM</AppButton>
        </div>
        <section class="product-section-actions"><h3>产品变更记录</h3>
          <p v-if="!productChangeRecords.length" class="muted">暂无产品变更记录。</p>
          <NCollapse><AppCollapseItem v-for="change in productChangeRecords" :key="change.id" :name="change.id" :title="`${store.localTime(change.created_at)} · ${change.changed_by_name} · ${change.reason}`">
            <p v-if="change.before && 'material' in change.before">变更前：{{ changeSummary(change.before) }}</p>
            <p v-if="'material' in change.after">变更后：{{ changeSummary(change.after) }}</p>
          </AppCollapseItem></NCollapse>
        </section>
      </template></template>
    </WorkspaceDocumentDialog>
  </section>
</template>
<style scoped>
/* 页面内的系列导航独立于应用主侧栏；右侧分页产品与 BOM 共用同一选中身份。 */
.product-workspace { display:grid; grid-template-columns:220px minmax(0,1fr); gap:20px; align-items:start; }
.product-series { position:sticky; top:16px; display:grid; gap:20px; min-width:0; padding:20px 14px; border:1px solid var(--workspace-field-border); border-radius:14px; background:var(--app-modal-surface); }
.series-heading { display:grid; gap:7px; padding:0 10px; }
.series-heading h3,.product-series-title h3,.product-bom-heading h3 { margin:0; }
.series-heading span,.series-empty,.product-series-title span,.product-bom-heading span { font-size:12px; }
.series-list { display:grid; gap:6px; max-height:55vh; overflow-y:auto; }
.series-item { display:grid; justify-items:start; gap:6px; width:100%; min-width:0; padding:14px 12px; border:1px solid transparent; border-radius:10px; text-align:left; white-space:normal; }
.series-item strong,.series-item small { overflow-wrap:anywhere; }
.series-item small { margin:0; font-size:12px; color:var(--workspace-field-muted); }
.series-item.is-active { border-color:var(--workspace-field-accent); background:var(--app-accent-tint); color:var(--workspace-field-accent); }
.series-empty { margin:0 10px; line-height:1.7; }
.series-manage { width:100%; }
.product-main { display:grid; gap:18px; min-width:0; }
.product-series-title,.product-bom-heading { display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap; }
.product-series-title>div:first-child,.product-bom-heading>div:first-child { display:grid; gap:7px; min-width:0; }
.product-bom-heading { padding:4px 2px 16px; }
.product-bom-heading h3,.product-bom-heading p { margin:0; overflow-wrap:anywhere; }
.product-bom-heading p { font-size:13px; }
.product-toolbar { display:flex; gap:10px; flex-wrap:wrap; }
.product-bom-panel { min-width:0; }
/* 产品切换压缩成配置卡片，BOM 始终是右侧主体；分页总数仍直接取服务端。 */
.product-picker { display:grid; gap:14px; min-width:0; padding:18px; border:1px solid var(--workspace-field-border); border-radius:14px; background:var(--app-modal-surface); }
.product-picker p { margin:0; font-size:13px; }
.product-options { display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:10px; max-height:170px; overflow-y:auto; }
.product-option { display:grid; justify-items:start; gap:7px; min-width:0; padding:12px 14px; border:1px solid var(--workspace-field-border); border-radius:10px; white-space:normal; text-align:left; }
.product-option strong,.product-option span { overflow-wrap:anywhere; }
.product-option span { color:var(--workspace-field-muted); font-size:12px; }
.product-option.is-active { border-color:var(--workspace-field-accent); background:var(--app-accent-tint); color:var(--workspace-field-accent); }
.product-query-error { color:var(--app-status-danger-text, #c65e62); }
@media(max-width:1100px) { .product-workspace { grid-template-columns:180px minmax(0,1fr); gap:14px; } }
@media(max-width:760px) { .product-workspace { grid-template-columns:minmax(0,1fr); } .product-series { position:static; } .series-list { grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); max-height:220px; } }
/* 筛选沿用公共表格，窄窗口换行而不撑宽整页；历史证据允许展开复制。 */
.product-filters { display:flex; flex-wrap:wrap; align-items:end; gap:12px; }
.product-filters label { min-width:160px; flex:1; }
small { display:block; margin-top:6px; }
.product-section-actions { margin:20px 0; }
.product-more { margin:16px 0; }
.product-more dl { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:16px; }
.product-more dt { color:var(--workspace-field-muted); font-size:12px; }
.product-more dd { margin:6px 0 0; white-space:pre-wrap; overflow-wrap:anywhere; }
</style>
