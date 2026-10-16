import assert from 'node:assert/strict'
import { test } from 'node:test'
import { productPreviewResponse, productPreviewProfiles, productPreviewMaterials, productPreviewOperations } from '../scripts/site-preview/product-fixtures.mjs'
import { productQueryBody, validateProductResult } from '../src/shared/product-api.ts'
import { validateMaterialResult } from '../src/shared/material-validation.ts'

const query = overrides => productQueryBody({query:'',kind:null,model_id:null,page:1,page_size:20,...overrides})
const scroll = {scroll:true}

test('默认产品预览仍仅有原三个产品，滚动样例不污染默认快照', () => {
  const original=productPreviewResponse('queryProducts',query())
  assert.equal(original.total,3)
  assert.deepEqual(original.items,productPreviewProfiles)
  assert.deepEqual(productPreviewResponse('materials'),productPreviewMaterials)
  productPreviewResponse('queryProducts',query(),scroll).items[0].material.name='调用方临时修改'
  const models=productPreviewResponse('productModels',undefined,scroll)
  models[1].child_count=999
  assert.deepEqual(productPreviewResponse('queryProducts',query()),original)
  assert.deepEqual(productPreviewResponse('productModels').map(row=>row.child_count),[1,2,0])
  assert.deepEqual(productPreviewResponse('queryProducts',query(),{scroll:false}),original)
})

test('滚动预览提供51个独立产品和20/20/11单页响应，详情物料与系列数量一致', () => {
  const pages=[1,2,3].map(page=>productPreviewResponse('queryProducts',query({page}),scroll))
  pages.forEach(page=>validateProductResult('queryProducts',page))
  assert.deepEqual(pages.map(page=>page.items.length),[20,20,11])
  assert.deepEqual(pages.map(page=>page.page),[1,2,3])
  assert.ok(pages.every(page=>page.total===51&&page.page_size===20))
  const profiles=pages.flatMap(page=>page.items)
  assert.equal(new Set(profiles.map(row=>row.id)).size,51)
  assert.equal(new Set(profiles.map(row=>row.material_id)).size,51)
  const materials=productPreviewResponse('materials',undefined,scroll)
  validateMaterialResult('materials',materials)
  assert.equal(materials.length,productPreviewMaterials.length+48)
  assert.equal(new Set(materials.map(row=>row.id)).size,materials.length)
  assert.equal(new Set(materials.map(row=>row.sku)).size,materials.length)
  for(const profile of profiles){
    const detail=productPreviewResponse('productDetail',{id:profile.id},scroll)
    validateProductResult('productDetail',detail)
    assert.deepEqual(detail,profile)
    assert.deepEqual(materials.find(row=>row.id===detail.material_id),detail.material)
  }
  const models=productPreviewResponse('productModels',undefined,scroll)
  validateProductResult('productModels',models)
  assert.deepEqual(models.map(row=>row.child_count),[1,50,0])
  for(const model of models){
    const detail=productPreviewResponse('productModelDetail',{id:model.id},scroll)
    validateProductResult('productModelDetail',detail)
    assert.equal(detail.child_count,profiles.filter(row=>row.model_id===model.id).length)
    assert.equal(productPreviewResponse('queryProducts',query({model_id:model.id}),scroll).total,detail.child_count)
  }
  const filtered=productPreviewResponse('queryProducts',query({query:'滚动示例控制板 48',model_id:2,kind:'semi_finished'}),scroll)
  validateProductResult('queryProducts',filtered)
  assert.equal(filtered.total,1);assert.equal(filtered.items[0].id,51)
  assert.equal(filtered.items[0].material.name,'滚动示例控制板 48')
  assert.deepEqual(productPreviewResponse('queryProducts',query({page:999}),scroll),pages[2])
})

test('滚动预览桥仅可读，所有产品及生产写入均明确拒绝且不更改快照', () => {
  const before=productPreviewResponse('queryProducts',query(),scroll)
  const writes=['createProduct','updateProduct','deleteProduct','createProductModel','updateProductModel',
    'deleteProductModel','createBom','activateBom','retireBom','cancelBom','createWorkOrder']
  for(const operation of writes){
    assert.equal(productPreviewOperations.includes(operation),false)
    assert.throws(()=>productPreviewResponse(operation,{id:1,version:1,reason:'不能写入'},scroll),/不支持此操作/)
  }
  assert.deepEqual(productPreviewResponse('queryProducts',query(),scroll),before)
})
