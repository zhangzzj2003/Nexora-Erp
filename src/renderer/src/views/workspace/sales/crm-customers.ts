import type { CrmForms, CrmKind, CrmOptions, CrmOverview } from '../../../../../shared/crm-api'

// 以已授权客户为入口聚合，不能由旧缓存中的联系记录反向扩充可见客户范围。
export function crmCustomerRows(options: CrmOptions | null, overview: CrmOverview | null) {
  return (options?.customers ?? []).map(customer => {
    const contacts = (overview?.contacts ?? []).filter(row => row.customer_id === customer.id)
    const activities = (overview?.activities ?? []).filter(row => row.customer_id === customer.id)
    const pending = activities.filter(row => row.status === 'planned').sort((a, b) => a.due_date.localeCompare(b.due_date) || a.id - b.id)
    return {
      ...customer, contacts, activities, pending,
      owner_name: options?.owners.find(row => row.id === customer.owner_id)?.name ?? (customer.owner_id == null ? '未分配' : `账号 #${customer.owner_id}`),
      contact_count: contacts.filter(row => row.is_active).length,
      pending_count: pending.length,
      overdue_count: pending.filter(row => row.overdue).length,
      next_followup: pending[0] ?? null,
    }
  })
}

// 从客户详情发起业务时清除其他客户的关联，保留同一客户尚未保存的正文。
export function selectCrmFormCustomer(forms: CrmForms, kind: CrmKind, customerId: number): void {
  const form = forms[kind]
  if (form.customer_id === customerId) return
  form.customer_id = customerId
  if ('contact_id' in form) form.contact_id = null
  if ('opportunity_id' in form) form.opportunity_id = null
}
