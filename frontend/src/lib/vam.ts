import type { VamAction, VamObjective, VamRole, VamTemplate, VamTreeNode, VamTrigger, VamWeights } from './api'

export const roles: Record<VamRole, string> = {
  tenant: '承租人', landlord: '出租人', company: '融资方', investor: '投资方', other: '其他合同方',
}
export const objectives: Record<VamObjective, string> = {
  cash: '现金负担', liability: '责任上限', timing: '付款灵活性', equity: '股权影响',
}
export const templates: Record<VamTemplate, string> = {
  qualitative: '条款与责任', repurchase: '回购付款', lease_exit: '提前退租负担',
}
export const triggers: Record<VamTrigger, string> = {
  met: '假设义务已触发', not_met: '假设义务未触发', unknown: '触发状态待确认',
}
export const scoreFields = {
  risk_score: '不利程度', feasibility_score: '应对条件', loss_score: '条件负担',
} as const
export const scoreKeys = Object.keys(scoreFields) as (keyof VamWeights)[]
export const defaultWeights: VamWeights = { risk_score: 40, feasibility_score: 35, loss_score: 25 }
export const fieldClass = 'min-h-11 w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary'

const repurchase = { principal: '10000000', annual_rate: '8', years: '3', interest: 'simple',
  extra_fee: '0', offset: '0', cap_mode: 'none', payment_days: '30' }
const lease = { deposit: '5000', penalty: '10000', extra_fee: '0', deposit_rule: 'add',
  cap_mode: 'none', payment_days: '15', early_exit_applies: true }
export const examples: {
  title: string; query: string; template: VamTemplate; role: VamRole; actions: VamAction[]
}[] = [
  {
    title: '对赌回购示例',
    query: '示例合同：投资本金 1000 万元。若自投资款到账起三年内累计净利润低于 3000 万元，由融资方在触发后 30 天内按年化 8% 单利回购。无其他费用或抵扣，原条款无责任上限。比较保留原条款与提出 1100 万元上限（假设对方接受）。',
    template: 'repurchase',
    role: 'company',
    actions: [
      { label: '原回购条款', terms: '按原条款回购。', parameters: repurchase },
      { label: '提议回购上限', terms: '假设对方接受修订，回购总额按下方参数封顶。',
        parameters: { ...repurchase, cap_mode: 'fixed', cap: '11000000' } },
    ],
  },
  {
    title: '提前退租示例',
    query: '示例合同：承租人提前退租且未获免责时，5000 元押金不退，另付 10000 元违约金，15 天内支付。无其他费用和上限。比较原条款与协商让没收的押金抵扣违约金（假设对方接受）。以第 6 个月退租且已确认通知与豁免条件为例。',
    template: 'lease_exit',
    role: 'tenant',
    actions: [
      { label: '原退租条款', terms: '押金不退，违约金另计。', parameters: lease },
      { label: '提议押金抵扣违约金', terms: '假设对方接受修订，没收的押金可抵扣违约金。',
        parameters: { ...lease, deposit_rule: 'offset' } },
    ],
  },
]

export function nodePath(branches: VamTreeNode[], id: string): VamTreeNode[] {
  for (const branch of branches) {
    if (branch.id === id) return [branch]
    const path = nodePath(branch.children, id)
    if (path.length) return [branch, ...path]
  }
  return []
}
