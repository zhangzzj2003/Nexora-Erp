import { ref } from 'vue'
import { materialDraft } from '../utils/material-form.ts'
import type { ProductPage, ProductQuery, ProductProfile, ProductKind, ProductModel, ProductChange } from '../../../shared/product-api'
import type { Bom } from '../../../shared/erp-api'

// 产品页、BOM 快捷建档与机型维护共用同一 Pinia 草稿，失败或切页不丢输入。
export function createProductState() {
  return {
    productQuery: ref<ProductQuery>({query: '', kind: null, model_id: null, page: 1, page_size: 20}),
    productResult: ref<ProductPage | null>(null), productModels: ref<ProductModel[]>([]),
    productsLoading: ref(false), productsError: ref(''),
    productDetailRecord: ref<ProductProfile | null>(null), productDetailId: ref(0),
    productDetailLoading: ref(false), productDetailError: ref(''),
    productBomRecords: ref<Bom[]>([]), productChangeRecords: ref<ProductChange[]>([]),
    productEditorOpen: ref(false), productReturnToBom: ref(false),
    productForm: ref({id: 0, version: 0, mode: 'new' as 'new' | 'existing' | 'edit', material_id: 0,
      kind: 'finished' as ProductKind, model_id: null as number | null, configuration_name: '', can_sell: true, can_purchase: true, can_produce: true, reason: ''}),
    productMaterialForm: ref(materialDraft()),
    productModelForm: ref({id: 0, version: 0, code: '', name: '', notes: '', reason: ''}),
    productModelChanges: ref<ProductChange[]>([]),
    bomDetailRecord: ref<Bom | null>(null), bomDetailLoading: ref(false), bomDetailError: ref(''),
  }
}
