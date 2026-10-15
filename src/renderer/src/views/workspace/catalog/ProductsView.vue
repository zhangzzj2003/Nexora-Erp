<script setup lang="ts">
import { computed, ref, watch, onUnmounted } from 'vue'
import { NCollapse } from 'naive-ui'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import { storeToRefs } from 'pinia'
import { useRoute } from 'vue-router'
import { usePiniaAppStore } from '../../../store/app-store'
import { productKindLabels } from '../../../../../shared/product-api'
import type { ProductProfile, ProductModel } from '../../../../../shared/product-api'
import type { Bom } from '../../../../../shared/erp-api'
import { materialChoiceFacts } from '../../../utils/material-selection'
import { captureDialogOrigin } from '../../../utils/dialog-origin'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import AppButton from '../../../components/app/AppButton.vue'
import AppStatusTag from '../../../components/app/AppStatusTag.vue'
import type { AppStatusTone } from '../../../components/app/AppStatusTag.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import ProductEditor from './ProductEditor.vue'
import ProductTreeSidebar from './ProductTreeSidebar.vue'
import ProductBomReuseDialog from './ProductBomReuseDialog.vue'
import ProductModelsDialog from './ProductModelsDialog.vue'
import BomEditor from './BomEditor.vue'
import BomDetailDialog from './BomDetailDialog.vue'
import ProductBomStructure from './ProductBomStructure.vue'
// 页面只组织展示，分页、草稿、版本写入和会话边界统一放在 Pinia。
const store = usePiniaAppStore(), route = useRoute()
const {productQuery: query, productResult: result, productModels: models, productsLoading, productsError,
  productDetailRecord: detail, productDetailId, productDetailLoading, productDetailError,
  productBomRecords, productChangeRecords, productEditorOpen, bomDetailRecord, bomDetailLoading, bomDetailError,
  materialCategories, boms, productModelForm, productModelChanges, busy, connectionLost} = storeToRefs(store)
const modelsOpen = ref(false), bomOpen = ref(false), detailsOpen = ref(false), reuseOpen = ref(false), createSeriesOnly = ref(false)
const versionsOpen = ref(false)
const pendingProductId = ref(0)
const bomTargetId = ref(0)
const selectedBomId = ref(0)
// 默认看启用版本，手动选择历史版本后保持到切换产品为止。
const selectedBom = computed(() => productBomRecords.value.find(row => row.id === selectedBomId.value)
  ?? productBomRecords.value.find(row => row.status === 'active') ?? productBomRecords.value[0])
watch(productDetailId, () => {selectedBomId.value = 0; versionsOpen.value = false})
const bomStatuses: Record<Bom['status'], {label:string; tone:AppStatusTone}> = {
  draft:{label:'草稿',tone:'pending'}, active:{label:'已启用',tone:'success'},
  retired:{label:'已停用',tone:'neutral'}, cancelled:{label:'已取消',tone:'danger'}
}
const versionOptions = computed(() => productBomRecords.value.map(row => ({value:row.id,
  label:`V${row.version} · ${bomStatuses[row.status].label}`})))
const productUnavailable = computed(() => busy.value || connectionLost.value || productDetailLoading.value || !!productDetailError.value)
function selectVersion(id: number): void {
  // 只接受当前产品已经加载的版本，禁用期间的迟到事件不能切换组成视图。
  if (!productUnavailable.value && productBomRecords.value.some(row => row.id === id)) selectedBomId.value = id
}
function viewComposition(id: number): void {
  if (productUnavailable.value) return
  selectVersion(id); versionsOpen.value = false
}
const seriesName = computed(() => models.value.find(row => row.id === query.value.model_id)?.name ?? '全部系列')
const bomColumns = [{key:'version',title:'BOM 版本',width:'110'}, {key:'status',title:'状态',width:'90'},
  {key:'source',title:'派生来源'}, {key:'actions',title:'操作',width:'390'}]
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
  if (!page) {store.closeProduct(); detailsOpen.value = false; reuseOpen.value = false; return}
  if (pendingProductId.value) {const id=pendingProductId.value; pendingProductId.value=0; void store.openProduct(id); return}
  const routeId = Number(rawId)
  if (Number.isSafeInteger(routeId) && routeId > 0 && consumedRoute !== String(rawId)) {
    consumedRoute = String(rawId); void store.openProduct(routeId); return
  }
  // 切换筛选时撤销旧读取，迟到的上一系列响应不能回填右侧。
  const selected = page.items.find(row => row.id === productDetailId.value) ?? page.items[0]
  if (selected && selected.id !== productDetailId.value) void store.openProduct(selected.id)
  else if (!selected) store.closeProduct()
}, {immediate:true})
// 保存后的定位意图不能跨账号、实例或权限边界执行。
watch(() => JSON.stringify([store.user?.id,store.server?.id,store.server?.fingerprint,store.user?.permissions.slice().sort()]), () => {
  pendingProductId.value=0; reuseOpen.value=false; modelsOpen.value=false; bomOpen.value=false; bomTargetId.value=0; versionsOpen.value=false
})
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
  pendingProductId.value=0; detailsOpen.value = false; store.closeProduct()
  query.value = {...query.value,model_id:id,query:'',kind:null,page:1}
}
function selectProduct(id: number): Promise<void> {
  pendingProductId.value=0; detailsOpen.value = false
  return store.openProduct(id)
}
function startBom(source?: Bom): void {
  if (detail.value && store.prepareProductBom(detail.value.material_id, source)) {
    bomTargetId.value=detail.value.material_id; reuseOpen.value=false; versionsOpen.value=false; bomOpen.value=true
  }
}
function newSeries(): void {
  if (!store.can('catalog.manage') || busy.value || connectionLost.value) return
  // 显式新建系列才退出原编辑模式，新建失败的同一份草稿继续保留。
  if (productModelForm.value.id) productModelForm.value={id:0,version:0,code:'',name:'',notes:'',reason:''}
  productModelChanges.value=[]; createSeriesOnly.value=true; modelsOpen.value=true
}
function newModel(mode:'new'|'existing'='new'): Promise<void> {
  const parent=query.value.model_id ?? detail.value?.model_id ?? null
  return store.startProduct(mode,0,false,parent)
}
function seriesSaved(model:ProductModel): void {selectSeries(model.id)}
function productSaved(row:ProductProfile): void {
  // 新子机型可能位于另一页，先保存定位意图，再刷新左侧目录和右侧 BOM。
  pendingProductId.value=row.id
  const unchanged=query.value.model_id===row.model_id && !query.value.query && query.value.kind===null
  query.value={...query.value,model_id:row.model_id,query:'',kind:null,page:1}
  if (unchanged) void store.queryProducts(1)
}
async function afterBomSaved(): Promise<void> {
  // 写后只刷新当前产品范围，不能把另一个产品的 BOM 显示在此详情中。
  if (productDetailId.value) await store.openProduct(productDetailId.value)
}
function changeSummary(value: ProductProfile): string {
  return [value.material.sku, value.material.name, productKindLabels[value.kind], value.model_name || '未归组',
    value.configuration_name || '未设置配置', value.can_sell === false ? '不可销售' : '可销售',
    value.can_purchase === false ? '不可采购' : '可采购', value.can_produce === false ? '不可生产' : '可生产', value.material.specification || '未填写规格', value.material.unit].join(' · ')
}
function sameModel(): void {
  if (!detail.value?.model_id) return
  detailsOpen.value = false; selectSeries(detail.value.model_id)
}
</script>
<template>
  <section class="product-workspace">
    <ProductTreeSidebar :models="models" :page="result" :query="query" :selected-id="productDetailId" :selected="detail"
      :loading="productsLoading" :error="productsError" :busy="busy" :disconnected="connectionLost" :can-manage="store.can('catalog.manage')"
      @series="selectSeries" @select="selectProduct" @new-series="newSeries" @new-model="newModel()" @include="newModel('existing')"
      @manage="createSeriesOnly=false;modelsOpen=true" @page-change="pageChange" @reset="reset" @retry="store.queryProducts()" />
    <div class="product-main">
    <section v-if="productDetailId" class="product-bom-panel" aria-label="选中产品的 BOM">
      <header v-if="detail" class="product-bom-heading">
        <div class="product-identity">
          <div class="product-meta"><span class="product-kind">{{ productKindLabels[detail.kind] }}</span><span class="product-code">{{ detail.material.sku }}</span><span v-if="detail.configuration_name && detail.configuration_name !== detail.material.name">{{ detail.configuration_name }}</span></div>
          <h3>{{ detail.material.name }}</h3>
          <p v-if="detail.material.spec_summary || detail.material.specification" class="muted">{{ detail.material.spec_summary || detail.material.specification }}</p>
        </div>
        <div class="product-toolbar">
          <AppButton size="small" :disabled="productUnavailable" @click.capture="captureDialogOrigin('product-detail',$event)" @click="detailsOpen = true">产品资料</AppButton>
          <AppButton v-if="store.can('bom.create') && store.can('production.view')" size="small" :disabled="productUnavailable" @click="reuseOpen = true">复用 BOM</AppButton>
          <AppButton v-if="store.can('bom.create')" size="small" variant="primary" :disabled="productUnavailable" @click="startBom()">新建版本</AppButton>
        </div>
      </header>
      <!-- 当前组成是工作区主体，历史表格按需打开，避免每次查看都占用一张卡片。 -->
      <template v-if="store.can('production.view')">
        <div v-if="productDetailLoading" class="bom-workspace-state" role="status">正在读取 BOM…</div>
        <div v-else-if="productDetailError" class="bom-workspace-state" role="alert"><p>{{ productDetailError }}</p><AppButton size="small" :disabled="busy || connectionLost" @click="afterBomSaved">重试</AppButton></div>
        <template v-else-if="selectedBom">
          <div class="bom-version-bar" aria-label="当前 BOM 版本">
            <div class="bom-version-choice"><span class="bom-version-label">BOM 版本</span>
              <WorkspaceSelect :model-value="selectedBom.id" :options="versionOptions" aria-label="选择 BOM 版本" size="small" :disabled="productUnavailable" @update:model-value="selectVersion" />
              <AppStatusTag :label="bomStatuses[selectedBom.status].label" :tone="bomStatuses[selectedBom.status].tone" />
            </div>
            <div class="product-toolbar"><AppButton size="small" :disabled="productUnavailable" @click="store.openBomDetail(selectedBom.id)">版本详情</AppButton>
              <AppButton size="small" :disabled="productUnavailable" @click.capture="captureDialogOrigin('product-bom-versions',$event)" @click="versionsOpen=true">版本管理 · {{ productBomRecords.length }}</AppButton></div>
          </div>
          <div v-if="selectedBom.source_bom" class="bom-source muted">复制来源：<AppButton variant="text" size="small" :disabled="productUnavailable" @click="store.openBomDetail(selectedBom.source_bom.id)">{{ selectedBom.source_bom.product_name }} · V{{ selectedBom.source_bom.version }}</AppButton></div>
          <ProductBomStructure :bom="selectedBom" :catalog="boms" :disabled="productUnavailable" @open="store.openBomDetail" />
        </template>
        <div v-else class="bom-workspace-state"><h4>尚未建立 BOM</h4><p class="muted">{{ store.can('bom.create') ? '新建版本，或复用已有 BOM 开始配置组成。' : '此产品暂无可查看的 BOM 版本。' }}</p></div>
      </template>
        <p v-if="!store.can('production.view')" class="muted">当前账号没有生产查看权限，关联 BOM 内容不加载。</p>
    </section>
    <section v-else class="bom-workspace-empty"><h3>BOM 工作区</h3><p class="muted">{{ productsLoading ? '正在读取子机型…' : productsError ? '左侧目录查询失败，请重试。' : `在左侧选择子机型，或在「${seriesName}」中新建子机型，再配置 BOM。` }}</p></section>
    </div>
    <ProductEditor v-if="!bomOpen && productEditorOpen" entity-label="子机型" @saved="productSaved" />
    <ProductModelsDialog v-model:show="modelsOpen" :create-only="createSeriesOnly" @saved="seriesSaved" />
    <ProductBomReuseDialog :show="reuseOpen && store.can('bom.create') && store.can('production.view')" :sources="boms" :target-name="detail ? `${detail.material.name} · ${detail.configuration_name || detail.material.sku}` : ''" :busy="busy" :disconnected="connectionLost" @update:show="reuseOpen=$event" @choose="startBom" />
    <BomEditor v-model:show="bomOpen" :target-material-id="bomTargetId || undefined" @saved="afterBomSaved" />
    <BomDetailDialog />
    <WorkspaceDocumentDialog origin-key="product-bom-versions" :show="versionsOpen && store.can('production.view') && !bomDetailRecord && !bomDetailLoading && !bomDetailError"
      read-only title="BOM 版本管理" lines-title="全部版本" :data="productBomRecords" :columns="bomColumns" :min-table-width="860"
      :ready="!productDetailLoading" :load-error="productDetailError" :busy="busy" @update:show="versionsOpen=$event" @invalidated="versionsOpen=false">
      <template #basicInfo><div v-if="detail" class="document-detail-field"><span>当前产品</span><strong>{{ detail.material.name }}</strong></div>
        <div v-if="detail" class="document-detail-field"><span>产品编码</span><strong>{{ detail.material.sku }}</strong></div>
        <div class="document-detail-field"><span>版本规则</span><strong>同一产品仅允许一个启用版本</strong></div></template>
      <template #cell-version="{row}"><strong>V{{ row.version }}</strong><small class="muted"> · #{{ row.id }}</small></template>
      <template #cell-status="{row}"><AppStatusTag :label="bomStatuses[row.status].label" :tone="bomStatuses[row.status].tone" /></template>
      <template #cell-source="{row}"><AppButton v-if="row.source_bom" variant="text" size="small" :disabled="productUnavailable" @click="store.openBomDetail(row.source_bom.id)">{{ row.source_bom.product_name }} · V{{ row.source_bom.version }}</AppButton><span v-else class="muted">独立创建</span></template>
      <template #cell-actions="{row}"><div class="form-actions">
        <AppButton size="small" :disabled="productUnavailable" @click="viewComposition(row.id)">{{ selectedBom?.id === row.id ? '当前组成' : '查看组成' }}</AppButton>
        <AppButton v-if="row.status !== 'cancelled' && store.can('bom.create')" size="small" :disabled="productUnavailable" @click="startBom(row)">复制派生</AppButton>
        <AppButton v-if="row.status === 'draft' && store.can('bom.activate')" size="small" tone="success" :disabled="productUnavailable || productBomRecords.some(item=>item.status==='active')" @click="store.activateBom(row.id).then(afterBomSaved)">启用</AppButton>
        <AppButton v-if="row.status === 'active' && store.can('bom.retire')" size="small" tone="warning" :disabled="productUnavailable" @click="store.retireBom(row.id).then(afterBomSaved)">停用</AppButton>
        <AppButton v-if="row.status === 'draft' && store.can('bom.cancel')" size="small" tone="error" :disabled="productUnavailable" @click="store.cancelBom(row.id).then(afterBomSaved)">取消草稿</AppButton>
      </div></template>
    </WorkspaceDocumentDialog>
    <WorkspaceDocumentDialog origin-key="product-detail" :show="showDetail" read-only title="产品资料" :data="[]" :columns="[]" :show-lines="false"
      :ready="!productDetailLoading" :load-error="productDetailError" :busy="busy" @update:show="detailsOpen = $event" @invalidated="detailsOpen = false">
      <template #basicInfo><template v-if="detail">
        <div class="document-detail-field"><span>产品编码</span><strong>{{ detail.material.sku }}</strong></div>
        <div class="document-detail-field"><span>产品名称</span><strong>{{ detail.material.name }}</strong></div>
        <div class="document-detail-field"><span>产品类型</span><strong>{{ productKindLabels[detail.kind] }}</strong></div>
        <div class="document-detail-field"><span>业务用途</span><strong>{{ [detail.can_sell !== false ? '可销售' : '不可销售',detail.can_purchase !== false ? '可采购' : '不可采购',detail.can_produce !== false ? '可生产' : '不可生产'].join(' · ') }}</strong></div>
        <div class="document-detail-field"><span>产品系列</span><strong>{{ detail.model_name || '未归组' }}</strong></div>
        <div class="document-detail-field"><span>配置</span><strong>{{ detail.configuration_name || '—' }}</strong></div>
        <div v-for="fact in facts" :key="fact.key" class="document-detail-field"><span>{{ fact.label }}</span><strong>{{ fact.value }}</strong></div>
      </template></template>
      <template #afterLines><template v-if="detail">
        <NCollapse v-if="technicalFacts.length" class="product-more"><AppCollapseItem name="specifications" title="规格与更多资料">
          <dl><div v-for="fact in technicalFacts" :key="fact.key"><dt>{{ fact.label }}</dt><dd>{{ fact.value }}</dd></div></dl>
        </AppCollapseItem></NCollapse>
        <div class="form-actions product-section-actions">
          <AppButton v-if="store.can('catalog.manage')" :disabled="busy || connectionLost" @click="store.startProduct('edit',detail.id)">编辑子机型</AppButton>
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
/* 既有主题控制颜色；产品头、版本栏和组成共用一个容器，减少重复卡片留白。 */
.product-workspace { display:grid; grid-template-columns:280px minmax(0,1fr); gap:16px; align-items:start; }
.product-main { min-width:0; }
.product-bom-panel { min-width:0; padding:20px; border:1px solid var(--workspace-field-border); border-radius:14px; background:var(--app-modal-background); }
.product-bom-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; flex-wrap:wrap; padding-bottom:18px; }
.product-identity { display:grid; gap:8px; min-width:0; flex:1 1 260px; }
.product-bom-heading h3,.product-bom-heading p { margin:0; overflow-wrap:anywhere; }
.product-bom-heading h3 { font-size:20px; line-height:1.4; }
.product-bom-heading p { font-size:13px; line-height:1.6; }
.product-meta { display:flex; align-items:center; gap:8px; flex-wrap:wrap; font-size:12px; color:var(--workspace-field-muted); }
.product-kind { border-radius:5px; padding:3px 7px; color:var(--workspace-field-accent); background:var(--app-accent-tint); font-weight:600; }
.product-code { font-variant-numeric:tabular-nums; overflow-wrap:anywhere; }
.product-toolbar { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.bom-version-bar { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; padding:14px 0; border-top:1px solid var(--workspace-field-border); border-bottom:1px solid var(--workspace-field-border); }
.bom-version-choice { display:flex; align-items:center; gap:10px; flex-wrap:wrap; min-width:0; }
.bom-version-label { font-size:12px; color:var(--workspace-field-muted); }
.bom-version-choice .workspace-select { width:170px; max-width:100%; }
.bom-source { display:flex; align-items:center; flex-wrap:wrap; gap:4px; padding-top:14px; font-size:12px; }
.bom-workspace-state { display:grid; justify-items:center; align-content:center; gap:12px; min-height:260px; text-align:center; }
.bom-workspace-state h4,.bom-workspace-state p { margin:0; overflow-wrap:anywhere; }
.bom-workspace-state[role='alert'] { color:var(--workspace-field-text); }
.bom-workspace-empty { display:grid; align-content:center; justify-items:center; gap:12px; min-height:360px; padding:32px; text-align:center; border:1px solid var(--workspace-field-border); border-radius:14px; background:var(--app-modal-surface); }
.bom-workspace-empty h3,.bom-workspace-empty p { margin:0; }
@media(max-width:1100px) { .product-workspace { grid-template-columns:260px minmax(0,1fr); gap:14px; } .product-bom-panel { padding:16px; } }
/* 桌面最小宽度仍保留两列，隐藏重复标签，为版本选择与状态留出同一行。 */
@media(max-width:1000px) { .bom-version-label { display:none; } .bom-version-choice .workspace-select { width:140px; } }
@media(max-width:760px) { .product-workspace { grid-template-columns:minmax(0,1fr); } .product-bom-heading h3 { font-size:18px; } }
.product-section-actions { margin:20px 0; }
.product-more { margin:16px 0; }
.product-more dl { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:16px; }
.product-more dt { color:var(--workspace-field-muted); font-size:12px; }
.product-more dd { margin:6px 0 0; white-space:pre-wrap; overflow-wrap:anywhere; }
</style>
