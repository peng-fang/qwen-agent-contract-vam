import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import type { VamAction, VamTemplate, VamWeights } from '@/lib/api'
import { fieldClass, scoreFields, scoreKeys } from '@/lib/vam'

type Field = {
  key: string
  label: string
  max?: number
  integer?: boolean
  options?: Record<string, string>
}
const commonFields: Field[] = [
  { key: 'extra_fee', label: '其他应付费用（元，无则填 0）' },
  { key: 'cap_mode', label: '责任上限（覆盖以上所有项目）', options: { none: '确认未设上限', fixed: '适用金额上限' } },
  { key: 'cap', label: '责任上限（元）' },
  { key: 'payment_days', label: '触发后付款期限（天）', max: 36600, integer: true },
]
const fieldsByTemplate: Record<VamTemplate, Field[]> = {
  qualitative: [],
  repurchase: [
    { key: 'principal', label: '回购本金（元）' },
    { key: 'annual_rate', label: '年利率（%）', max: 100 },
    { key: 'years', label: '从约定起算点计的整年数', integer: true, max: 30 },
    { key: 'interest', label: '计息方式', options: { simple: '单利', compound: '按年复利' } },
    { key: 'offset', label: '抵扣金额（元，无则填 0）' },
    ...commonFields,
  ],
  lease_exit: [
    { key: 'deposit', label: '押金（元）' },
    { key: 'penalty', label: '违约金（元）' },
    { key: 'deposit_rule', label: '押金与违约金的关系', options: {
      add: '没收押金，并另付违约金', offset: '没收押金，且抵扣违约金', refund: '退还押金',
    } },
    ...commonFields,
  ],
}

export function ActionFields({ actions, template, onChange }: {
  actions: VamAction[]
  template: VamTemplate
  onChange: (value: VamAction[]) => void
}) {
  function update(index: number, action: VamAction) {
    onChange(actions.map((item, i) => i === index ? action : item))
  }
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-medium">待比较方案</h3>
        <Button type="button" variant="outline" className="min-h-11" disabled={actions.length >= 3}
          onClick={() => onChange([...actions, { label: '', terms: '', parameters: {} }])}>添加方案</Button>
      </div>
      {actions.length === 0 && <p className="text-sm text-muted-foreground">可以先看情景。添加两个方案后可比较同一情景下的后果。</p>}
      <div className="grid gap-3 lg:grid-cols-2">
        {actions.map((action, index) => (
          <section key={index} className="min-w-0 space-y-3 rounded-lg border p-3">
            <div className="flex items-end gap-2">
              <label className="min-w-0 flex-1 space-y-1 text-sm">
                <span>方案 {index + 1} 名称</span>
                <input className={fieldClass} value={action.label} maxLength={80} required
                  placeholder={index === 0 ? '例如：保留原条款' : '例如：提出责任上限'}
                  onChange={(e) => update(index, { ...action, label: e.target.value })} />
              </label>
              <Button type="button" variant="ghost" className="min-h-11" aria-label={'删除方案 ' + (index + 1)}
                onClick={() => onChange(actions.filter((_, i) => i !== index))}>删除</Button>
            </div>
            <label className="block space-y-1 text-sm">
              <span>方案条款或成立条件</span>
              <Textarea rows={2} maxLength={1200} value={action.terms} placeholder="例如：只有对方接受修订，上限才生效"
                onChange={(e) => update(index, { ...action, terms: e.target.value })} />
            </label>
            {template !== 'qualitative' && (
              <div className="grid gap-3 sm:grid-cols-2">
                {fieldsByTemplate[template].filter((field) => field.key !== 'cap' || action.parameters.cap_mode === 'fixed').map((field) => {
                  const value = String(action.parameters[field.key] ?? '')
                  const set = (next: string) => update(index, { ...action, parameters: { ...action.parameters, [field.key]: next } })
                  return (
                    <label key={field.key} className="min-w-0 space-y-1 text-sm">
                      <span>{field.label}</span>
                      {field.options ? (
                        <select className={fieldClass} value={value} onChange={(e) => set(e.target.value)}>
                          <option value="">待确认</option>
                          {Object.entries(field.options).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
                        </select>
                      ) : (
                        <input className={fieldClass} type="number" min="0" max={field.max ?? 1e12}
                          step={field.integer ? 1 : 'any'} placeholder="待确认" value={value}
                          onChange={(e) => set(e.target.value)} />
                      )}
                    </label>
                  )
                })}
                {template === 'lease_exit' && (
                  <label className="flex min-h-11 items-center gap-2 text-sm sm:col-span-2">
                    <input type="checkbox" checked={action.parameters.early_exit_applies === true}
                      onChange={(e) => update(index, { ...action, parameters: { ...action.parameters, early_exit_applies: e.target.checked } })} />
                    已确认这些参数适用于当前退租月份、通知和豁免条件
                  </label>
                )}
              </div>
            )}
          </section>
        ))}
      </div>
    </div>
  )
}

export function WeightInputs({ value, onChange }: { value: VamWeights; onChange: (value: VamWeights) => void }) {
  return (
    <div className="space-y-2">
      <div className="grid gap-2 sm:grid-cols-3">
        {scoreKeys.map((key) => (
          <label key={key} className="space-y-1 text-sm">
            <span>{scoreFields[key]}权重（%）</span>
            <input className={fieldClass} type="number" min={0} max={100} step={1} value={value[key]}
              onChange={(e) => onChange({ ...value, [key]: Number(e.target.value) })} />
          </label>
        ))}
      </div>
      <p className="text-sm text-muted-foreground">合计 {scoreKeys.reduce((sum, key) => sum + value[key], 0)}%。权重需合计 100%。</p>
    </div>
  )
}
