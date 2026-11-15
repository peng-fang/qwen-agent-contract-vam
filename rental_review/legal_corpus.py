"""中国内地租房合同审查的本地法律依据库（条文要旨，非逐字引用）。

设计约束：
- 只保留与租房、格式条款、违约金/定金相关的《民法典》条文；
- 返回“条文要旨 + 条号 + 官方来源”，不伪造判决或地方政策；
- 检索是确定性的关键词匹配，模型不能自行编造法条。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

_CIVIL_CODE_URL = 'https://www.gov.cn/xinwen/2020-06/01/content_5516649.htm'


@dataclass(frozen=True)
class LegalArticle:
    article_id: str
    article: str
    title: str
    summary: str
    keywords: tuple[str, ...]
    source: str = '《中华人民共和国民法典》'
    source_url: str = _CIVIL_CODE_URL
    jurisdiction: str = 'mainland'
    contract_types: tuple[str, ...] = ('general', 'rental')
    is_definition: bool = False

    def to_dict(self) -> dict:
        return {
            'article_id': self.article_id,
            'article': self.article,
            'title': self.title,
            'summary': self.summary,
            'source': self.source,
            'source_url': self.source_url,
            'jurisdiction': self.jurisdiction,
            'contract_types': list(self.contract_types),
            'note': '条文要旨，非逐字引用；具体适用需结合完整条文和案件事实。',
        }


ARTICLES: tuple[LegalArticle, ...] = (
    LegalArticle('art703', '第七百零三条', '租赁合同定义',
                 '出租人将租赁物交付承租人使用、收益，承租人支付租金。',
                 ('租赁', '出租', '承租人', '租金'), is_definition=True),
    LegalArticle('art704', '第七百零四条', '租赁合同主要内容',
                 '租赁合同一般包括租赁物名称、数量、用途、租赁期限、租金及其支付期限和方式、维修等条款。',
                 ('租赁期限', '租金', '维修', '支付方式', '押金')),
    LegalArticle('art705', '第七百零五条', '租赁期限上限',
                 '租赁期限不得超过二十年；超过部分无效。',
                 ('租赁期限', '二十年', '续租', '期限')),
    LegalArticle('art706', '第七百零六条', '登记备案不影响合同效力',
                 '当事人未办理租赁登记备案手续，不影响租赁合同效力。',
                 ('备案', '登记', '合同效力')),
    LegalArticle('art707', '第七百零七条', '六个月以上租赁应书面',
                 '租赁期限六个月以上的，应当采用书面形式；未采用书面形式且无法确定租赁期限的，视为不定期租赁。',
                 ('六个月', '书面', '不定期', '租赁期限')),
    LegalArticle('art708', '第七百零八条', '出租人交付义务',
                 '出租人应当按照约定将租赁物交付承租人，并在租赁期间保持租赁物符合约定用途。',
                 ('交付', '房屋', '约定用途', '维修')),
    LegalArticle('art709', '第七百零九条', '承租人按约定使用',
                 '承租人应当按照约定的方法使用租赁物；无约定或约定不明时，按租赁物性质使用。',
                 ('使用', '约定用途', '房屋')),
    LegalArticle('art710', '第七百一十条', '正常损耗不赔',
                 '承租人按照约定方法或租赁物性质使用，致使租赁物损耗的，不承担赔偿责任。',
                 ('损耗', '正常使用', '赔偿', '折旧')),
    LegalArticle('art711', '第七百一十一条', '不当使用可解除',
                 '承租人未按约定方法或租赁物性质使用，造成损失的，出租人可以解除合同并请求赔偿。',
                 ('不当使用', '解除', '赔偿', '损坏')),
    LegalArticle('art712', '第七百一十二条', '出租人维修义务',
                 '出租人应当履行租赁物的维修义务，但当事人另有约定的除外。',
                 ('维修', '修理', '房东', '出租人')),
    LegalArticle('art713', '第七百一十三条', '维修请求与费用',
                 '承租人可以请求出租人在合理期限内维修；出租人未维修的，承租人可自行维修，费用由出租人负担。因维修影响使用的，应相应减少租金或延长租期。',
                 ('维修', '修理', '费用', '租金减免', '延长租期')),
    LegalArticle('art714', '第七百一十四条', '承租人保管义务',
                 '承租人应妥善保管租赁物；因保管不善造成毁损、灭失的，应承担赔偿责任。',
                 ('保管', '毁损', '灭失', '赔偿')),
    LegalArticle('art715', '第七百一十五条', '改善或增设他物',
                 '承租人经出租人同意，可以对租赁物进行改善或增设他物；未经同意，出租人可要求恢复原状或赔偿损失。',
                 ('装修', '改造', '增设', '恢复原状', '赔偿')),
    LegalArticle('art716', '第七百一十六条', '转租',
                 '承租人经出租人同意，可以将租赁物转租给第三人；未经同意转租的，出租人可以解除合同。',
                 ('转租', '第三人', '解除')),
    LegalArticle('art721', '第七百二十一条', '租金支付期限',
                 '承租人应按约定期限支付租金；对支付期限没有约定或约定不明的，依照本法第五百一十条确定。',
                 ('租金', '支付期限', '逾期')),
    LegalArticle('art722', '第七百二十二条', '欠租解除',
                 '承租人无正当理由未支付或迟延支付租金，经催告后在合理期限内仍不支付的，出租人可以解除合同。',
                 ('欠租', '迟延', '催告', '解除')),
    LegalArticle('art724', '第七百二十四条', '非承租人原因无法使用',
                 '因不可归责于承租人的事由，致使租赁物部分或全部毁损、灭失，不能实现合同目的的，承租人可以解除合同。',
                 ('无法使用', '毁损', '灭失', '解除')),
    LegalArticle('art725', '第七百二十五条', '买卖不破租赁',
                 '租赁物在承租人按照租赁合同占有期限内发生所有权变动的，不影响租赁合同效力。',
                 ('买卖', '所有权变动', '继续租', '房东出售')),
    LegalArticle('art729', '第七百二十九条', '租赁物毁损减租',
                 '因不可归责于承租人的事由致使租赁物部分或全部毁损、灭失的，承租人可以请求减少租金或不支付租金；不能实现合同目的的，可以解除合同。',
                 ('毁损', '减少租金', '解除')),
    LegalArticle('art730', '第七百三十条', '期限不明',
                 '当事人对租赁期限没有约定或约定不明，依据本法第五百一十条仍不能确定的，视为不定期租赁；当事人可以随时解除合同，但应在合理期限前通知对方。',
                 ('不定期', '期限不明', '随时解除', '通知')),
    LegalArticle('art731', '第七百三十一条', '危及安全健康',
                 '租赁物危及承租人安全或健康的，即使承租人订立合同时明知该租赁物质量不合格，承租人仍可以随时解除合同。',
                 ('安全', '健康', '甲醛', '解除')),
    LegalArticle('art733', '第七百三十三条', '返还租赁物',
                 '租赁期限届满，承租人应返还租赁物；返还的租赁物应符合按照约定或根据租赁物性质使用后的状态。',
                 ('返还', '到期', '押金', '房屋状态')),
    LegalArticle('art734', '第七百三十四条', '续租与优先承租',
                 '租赁期限届满，承租人继续使用租赁物且出租人未提出异议的，原租赁合同继续有效，但租赁期限为不定期。房屋承租人享有以同等条件优先承租的权利。',
                 ('续租', '优先承租', '继续使用', '不定期')),
    LegalArticle('art496', '第四百九十六条', '格式条款提示说明',
                 '采用格式条款订立合同的，提供格式条款的一方应遵循公平原则确定权利义务，并采取合理方式提示对方注意免除或减轻其责任等与对方有重大利害关系的条款，按对方要求说明。',
                 ('格式条款', '提示', '说明', '免责', '重大利害关系')),
    LegalArticle('art497', '第四百九十七条', '格式条款无效',
                 '提供格式条款一方不合理地免除或减轻其责任、加重对方责任、限制对方主要权利，或排除对方主要权利的，该格式条款无效。',
                 ('格式条款', '无效', '加重责任', '限制权利', '免责')),
    LegalArticle('art585', '第五百八十五条', '违约金',
                 '当事人可以约定违约金；约定的违约金低于造成的损失，可请求增加；过分高于造成的损失，可请求适当减少。',
                 ('违约金', '过高', '损失', '调整')),
    LegalArticle('art587', '第五百八十七条', '定金',
                 '债务人履行债务的，定金应抵作价款或收回；给付定金一方不履行债务或履行不符合约定，致使不能实现合同目的的，无权请求返还定金；收受定金一方不履行的，应双倍返还定金。',
                 ('定金', '押金', '双倍返还', '不退还')),
    LegalArticle('art509', '第五百零九条', '全面履行与诚信',
                 '当事人应按照约定全面履行自己的义务，并遵循诚信原则，根据合同性质、目的和交易习惯履行通知、协助、保密等义务。',
                 ('履行', '诚信', '通知', '协助')),
    LegalArticle('art577', '第五百七十七条', '违约责任',
                 '当事人一方不履行合同义务或履行不符合约定的，应承担继续履行、采取补救措施或赔偿损失等违约责任。',
                 ('违约', '赔偿', '继续履行', '补救')),

    # ------------------------------------------------------------------
    # 中国内地：买卖/采购、借款/担保、劳动、消费者格式条款
    # ------------------------------------------------------------------
    LegalArticle('art595', '第五百九十五条', '买卖合同定义',
                 '买卖合同是出卖人转移标的物所有权于买受人，买受人支付价款的合同。',
                 ('买卖', '采购', '交付', '价款'),
                 contract_types=('procurement',)),
    LegalArticle('art596', '第五百九十六条', '买卖合同主要内容',
                 '买卖合同一般包括标的物名称、数量、质量、价款、履行期限、履行地点和方式、包装、检验标准和方法等条款。',
                 ('采购', '质量', '验收', '价款', '交付'),
                 contract_types=('procurement',)),
    LegalArticle('art598', '第五百九十八条', '出卖人交付义务',
                 '出卖人应当履行向买受人交付标的物或者交付提取标的物的单证，并转移标的物所有权的义务。',
                 ('交付', '所有权', '采购'),
                 contract_types=('procurement',)),
    LegalArticle('art601', '第六百零一条', '交付期限',
                 '出卖人应当按照约定的时间交付标的物；约定交付期限的，可以在该期限内的任何时间交付。',
                 ('交付期限', '逾期', '采购'),
                 contract_types=('procurement',)),
    LegalArticle('art617', '第六百一十七条', '质量不符合要求',
                 '出卖人交付的标的物不符合质量要求的，买受人可以依据本法第五百八十二条至第五百八十四条的规定请求承担违约责任。',
                 ('质量', '不符合', '验收', '违约', '采购'),
                 contract_types=('procurement',)),
    LegalArticle('art667', '第六百六十七条', '借款合同定义',
                 '借款合同是借款人向贷款人借款，到期返还借款并支付利息的合同。',
                 ('借款', '贷款', '利息', '还款'),
                 contract_types=('loan',)),
    LegalArticle('art670', '第六百七十条', '借款利息',
                 '借款的利息不得预先在本金中扣除；利息预先在本金中扣除的，应当按照实际借款数额返还借款并计算利息。',
                 ('利息', '本金', '砍头息', '借款'),
                 contract_types=('loan',)),
    LegalArticle('art674', '第六百七十四条', '逾期利息',
                 '借款人未按照约定的期限返还借款的，应当按照约定或者国家有关规定支付逾期利息。',
                 ('逾期', '利息', '还款', '借款'),
                 contract_types=('loan',)),
    LegalArticle('art681', '第六百八十一条', '保证合同定义',
                 '保证合同是为保障债权的实现，保证人和债权人约定，当债务人不履行到期债务或者发生当事人约定的情形时，保证人履行债务或者承担责任的合同。',
                 ('保证', '担保', '债务', '债权人'),
                 contract_types=('loan',)),
    LegalArticle('art686', '第六百八十六条', '保证方式',
                 '保证的方式包括一般保证和连带责任保证；当事人在保证合同中对保证方式没有约定或者约定不明确的，按照一般保证承担保证责任。',
                 ('保证', '连带责任', '担保', '保证方式'),
                 contract_types=('loan',)),

    LegalArticle('lab10', '《劳动合同法》第十条', '书面劳动合同',
                 '建立劳动关系，应当订立书面劳动合同；已建立劳动关系，未同时订立书面劳动合同的，应当自用工之日起一个月内订立。',
                 ('劳动合同', '书面', '用工', '劳动关系'),
                 source='《中华人民共和国劳动合同法》', source_url='https://flk.npc.gov.cn/',
                 contract_types=('labor',)),
    LegalArticle('lab17', '《劳动合同法》第十七条', '劳动合同内容',
                 '劳动合同应当具备用人单位、劳动者、合同期限、工作内容和地点、工作时间和休息休假、劳动报酬、社会保险、劳动保护等条款。',
                 ('劳动合同', '工资', '工作地点', '社保', '期限'),
                 source='《中华人民共和国劳动合同法》', source_url='https://flk.npc.gov.cn/',
                 contract_types=('labor',)),
    LegalArticle('lab19', '《劳动合同法》第十九条', '试用期',
                 '劳动合同期限三个月以上不满一年的，试用期不得超过一个月；一年以上不满三年的，不得超过二个月；三年以上固定期限和无固定期限的，不得超过六个月。同一用人单位与同一劳动者只能约定一次试用期。',
                 ('试用期', '劳动合同', '期限'),
                 source='《中华人民共和国劳动合同法》', source_url='https://flk.npc.gov.cn/',
                 contract_types=('labor',)),
    LegalArticle('lab23', '《劳动合同法》第二十三条', '保密与竞业限制',
                 '用人单位与劳动者可以约定保守商业秘密和与知识产权相关的保密事项；对负有保密义务的劳动者，可以约定竞业限制条款，并在解除或终止劳动合同后按月给予经济补偿。',
                 ('竞业限制', '保密', '补偿', '劳动合同'),
                 source='《中华人民共和国劳动合同法》', source_url='https://flk.npc.gov.cn/',
                 contract_types=('labor',)),
    LegalArticle('lab26', '《劳动合同法》第二十六条', '劳动合同无效',
                 '以欺诈、胁迫的手段或者乘人之危，使对方在违背真实意思的情况下订立或者变更劳动合同的，劳动合同无效或者部分无效；用人单位免除自己的法定责任、排除劳动者权利的，劳动合同无效或者部分无效。',
                 ('劳动合同', '无效', '免责', '排除权利'),
                 source='《中华人民共和国劳动合同法》', source_url='https://flk.npc.gov.cn/',
                 contract_types=('labor',)),
    LegalArticle('lab39', '《劳动合同法》第三十九条', '用人单位单方解除',
                 '劳动者严重违反规章制度、严重失职营私舞弊、同时与其他用人单位建立劳动关系严重影响本单位工作任务等情形，用人单位可以解除劳动合同。',
                 ('解除', '单方解除', '严重违反', '劳动合同'),
                 source='《中华人民共和国劳动合同法》', source_url='https://flk.npc.gov.cn/',
                 contract_types=('labor',)),

    LegalArticle('consumer26', '《消费者权益保护法》第二十六条', '格式条款与不公平规定',
                 '经营者在经营活动中使用格式条款的，应当以显著方式提请消费者注意商品或者服务的数量和质量、价款或者费用、履行期限和方式、安全注意事项和风险警示、售后服务、民事责任等与消费者有重大利害关系的内容，并按照消费者的要求予以说明。经营者不得以格式条款、通知、声明、店堂告示等方式，作出排除或者限制消费者权利、减轻或者免除经营者责任、加重消费者责任等对消费者不公平、不合理的规定。',
                 ('格式条款', '消费者', '不公平', '免责', '自动续费'),
                 source='《中华人民共和国消费者权益保护法》', source_url='https://www.gov.cn/',
                 contract_types=('consumer', 'ecommerce')),

    # ------------------------------------------------------------------
    # 中国内地：借款/担保、消费/电商、加盟、争议解决
    # ------------------------------------------------------------------
    LegalArticle('art680', '第六百八十条', '禁止高利放贷',
                 '禁止高利放贷，借款的利率不得违反国家有关规定；借款合同对支付利息没有约定的，视为没有利息。',
                 ('高利', '利率', '利息', '借款'),
                 contract_types=('loan',)),
    LegalArticle('art691', '第六百九十一条', '保证范围',
                 '保证的范围包括主债权及其利息、违约金、损害赔偿金和实现债权的费用；当事人另有约定的，按照约定。',
                 ('保证范围', '担保', '违约金', '实现债权费用'),
                 contract_types=('loan',)),
    LegalArticle('art692', '第六百九十二条', '保证期间',
                 '保证期间是确定保证人承担保证责任的期间，不发生中止、中断和延长；债权人与保证人可以约定保证期间。',
                 ('保证期间', '担保', '保证责任'),
                 contract_types=('loan',)),

    LegalArticle('consumer25', '《消费者权益保护法》第二十五条', '七天无理由退货',
                 '经营者采用网络、电视、电话、邮购等方式销售商品，消费者有权自收到商品之日起七日内退货，且无需说明理由；定作、鲜活易腐、已拆封音像制品/软件、报纸期刊等除外。',
                 ('七天', '七日', '无理由', '退货', '电商'),
                 source='《中华人民共和国消费者权益保护法》', source_url='https://www.gov.cn/',
                 contract_types=('ecommerce', 'consumer')),
    LegalArticle('ecommerce17', '《电子商务法》第十七条', '商品信息披露',
                 '电子商务经营者应当全面、真实、准确、及时地披露商品或者服务信息，保障消费者的知情权和选择权；不得以虚构交易、编造用户评价等方式进行虚假或者引人误解的商业宣传。',
                 ('电商', '宣传', '商品信息', '虚假宣传', '描述'),
                 source='《中华人民共和国电子商务法》', source_url='https://www.gov.cn/',
                 contract_types=('ecommerce',)),
    LegalArticle('ecommerce18', '《电子商务法》第十八条', '搜索结果与自然结果',
                 '电子商务经营者根据消费者的兴趣爱好、消费习惯等特征向其提供商品或者服务的搜索结果的，应当同时向该消费者提供不针对其个人特征的选项，尊重和平等保护消费者合法权益。',
                 ('电商', '搜索', '个性化', '消费者'),
                 source='《中华人民共和国电子商务法》', source_url='https://www.gov.cn/',
                 contract_types=('ecommerce',)),
    LegalArticle('ecommerce38', '《电子商务法》第三十八条', '平台责任',
                 '电子商务平台经营者知道或者应当知道平台内经营者销售的商品或者提供的服务不符合保障人身、财产安全的要求，或者有其他侵害消费者合法权益行为，未采取必要措施的，依法与该平台内经营者承担连带责任。',
                 ('平台', '连带责任', '电商', '消费者'),
                 source='《中华人民共和国电子商务法》', source_url='https://www.gov.cn/',
                 contract_types=('ecommerce',)),

    LegalArticle('franchise3', '《商业特许经营管理条例》第三条', '商业特许经营定义',
                 '商业特许经营是指拥有注册商标、企业标志、专利、专有技术等经营资源的企业，以合同形式将其拥有的经营资源许可其他经营者使用，被特许人按照合同约定在统一的经营模式下开展经营，并向特许人支付特许经营费用的经营活动。',
                 ('加盟', '特许经营', '加盟费', '经营资源'),
                 source='《商业特许经营管理条例》', source_url='https://www.gov.cn/',
                 contract_types=('franchise',)),
    LegalArticle('franchise7', '《商业特许经营管理条例》第七条', '两店一年',
                 '特许人从事特许经营活动应当拥有至少2个直营店，并且经营时间超过1年。',
                 ('加盟', '特许人', '直营店', '两店一年'),
                 source='《商业特许经营管理条例》', source_url='https://www.gov.cn/',
                 contract_types=('franchise',)),
    LegalArticle('franchise11', '《商业特许经营管理条例》第十一条', '特许经营合同内容',
                 '从事特许经营活动，特许人和被特许人应当采用书面形式订立特许经营合同；合同应约定特许经营内容、期限、费用、培训、支持、保密、违约责任和争议解决等。',
                 ('加盟', '特许经营合同', '加盟费', '期限', '违约责任'),
                 source='《商业特许经营管理条例》', source_url='https://www.gov.cn/',
                 contract_types=('franchise',)),
    LegalArticle('franchise12', '《商业特许经营管理条例》第十二条', '冷静期解除',
                 '特许人和被特许人应当在特许经营合同中约定，被特许人在特许经营合同订立后一定期限内，可以单方解除合同。',
                 ('加盟', '冷静期', '单方解除', '特许经营'),
                 source='《商业特许经营管理条例》', source_url='https://www.gov.cn/',
                 contract_types=('franchise',)),
    LegalArticle('franchise21', '《商业特许经营管理条例》第二十一条', '信息披露',
                 '特许人应当在订立特许经营合同之日前至少30日，以书面形式向被特许人披露特许人及其从事特许经营活动的基本情况、经营资源、加盟费用、投资预算等信息。',
                 ('加盟', '信息披露', '加盟费', '投资预算'),
                 source='《商业特许经营管理条例》', source_url='https://www.gov.cn/',
                 contract_types=('franchise',)),

    LegalArticle('cpl35', '《民事诉讼法》第三十五条', '协议管辖',
                 '合同或者其他财产权益纠纷的当事人可以书面协议选择被告住所地、合同履行地、合同签订地、原告住所地、标的物所在地等与争议有实际联系的地点的人民法院管辖，但不得违反级别管辖和专属管辖的规定。',
                 ('管辖', '协议管辖', '法院', '争议解决'),
                 source='《中华人民共和国民事诉讼法》', source_url='https://www.gov.cn/',
                 contract_types=('dispute',)),
    LegalArticle('arb4', '《仲裁法》第四条', '仲裁协议',
                 '当事人采用仲裁方式解决纠纷，应当双方自愿，达成仲裁协议；没有仲裁协议，一方申请仲裁的，仲裁委员会不予受理。',
                 ('仲裁', '仲裁协议', '争议解决'),
                 source='《中华人民共和国仲裁法》', source_url='https://www.gov.cn/',
                 contract_types=('dispute',)),
    LegalArticle('arb16', '《仲裁法》第十六条', '仲裁协议内容',
                 '仲裁协议包括合同中订立的仲裁条款和以其他书面方式在纠纷发生前或者纠纷发生后达成的请求仲裁的协议；仲裁协议应当具有请求仲裁的意思表示、仲裁事项和选定的仲裁委员会。',
                 ('仲裁', '仲裁协议', '仲裁委员会', '争议解决'),
                 source='《中华人民共和国仲裁法》', source_url='https://www.gov.cn/',
                 contract_types=('dispute',)),
    LegalArticle('arb18', '《仲裁法》第十八条', '仲裁协议不明确',
                 '仲裁协议对仲裁事项或者仲裁委员会没有约定或者约定不明确的，当事人可以补充协议；达不成补充协议的，仲裁协议无效。',
                 ('仲裁', '约定不明', '仲裁委员会', '争议解决'),
                 source='《中华人民共和国仲裁法》', source_url='https://www.gov.cn/',
                 contract_types=('dispute',)),

    # ------------------------------------------------------------------
    # 中国香港：租约、不合情理合约、货物买卖
    # ------------------------------------------------------------------
    LegalArticle('hk-cap7-s2', '香港法例第7章第2条', '业主与租客定义',
                 '《业主与租客（综合）条例》界定“业主”“租客”“租赁”“处所”等概念，租约可以是书面或口头协议。',
                 ('租约', '业主', '租客', '租赁', '按金'),
                 source='香港法例第7章《業主與租客（綜合）條例》',
                 source_url='https://www.elegislation.gov.hk/hk/cap7',
                 jurisdiction='hongkong', contract_types=('rental',), is_definition=True),
    LegalArticle('hk-cap7-s9b', '香港法例第7章第9B条', '租金调整须双方协议',
                 '受该部适用的租赁，租金按业主与租客协议调整；租金调整须按指定表格通知差饷物业估价署署长，未经有效通知的加租可能影响追收。',
                 ('加租', '租金调整', '租约', '通知'),
                 source='香港法例第7章《業主與租客（綜合）條例》',
                 source_url='https://www.elegislation.gov.hk/hk/cap7',
                 jurisdiction='hongkong', contract_types=('rental',)),
    LegalArticle('hk-cap7-s52', '香港法例第7章第52条', '租约延续与终止',
                 '在有关部适用的情况下，租约或分租契因期限届满或业主终止而结束时，租客可获延续保障；具体适用取决于租约是否属于受保护/受规管租约。',
                 ('租约', '续租', '终止', '收楼', '通知'),
                 source='香港法例第7章《業主與租客（綜合）條例》',
                 source_url='https://www.elegislation.gov.hk/hk/cap7',
                 jurisdiction='hongkong', contract_types=('rental',)),
    LegalArticle('hk-cap458-s5', '香港法例第458章第5条', '不合情理合约的救济',
                 '如法庭裁定消费者合约或其部分在订立时属不合情理，可拒绝执行、只执行其余部分，或限制/修订不合情理部分以避免不合情理结果。',
                 ('不合情理', '不公平', '消费者', '免责', '租约'),
                 source='香港法例第458章《不合情理合約條例》',
                 source_url='https://www.elegislation.gov.hk/hk/cap458',
                 jurisdiction='hongkong', contract_types=('rental', 'consumer', 'procurement', 'ecommerce', 'franchise')),
    LegalArticle('hk-cap458-s6', '香港法例第458章第6条', '判断不合情理的因素',
                 '法庭可考虑双方议价能力、消费者是否理解文件、是否受到不当压力或不公平手法、条件是否超出保护合法利益所需，以及同类货品/服务的替代价格等因素。',
                 ('不合情理', '议价能力', '不当压力', '不公平', '消费者'),
                 source='香港法例第458章《不合情理合約條例》',
                 source_url='https://www.elegislation.gov.hk/hk/cap458',
                 jurisdiction='hongkong', contract_types=('rental', 'consumer', 'procurement', 'ecommerce', 'franchise')),
    LegalArticle('hk-cap26-s14', '香港法例第26章第14条', '货物买卖的隐含条款',
                 '《货品售卖条例》就卖方对货物所有权、品质/适销性、用途适用性等作出隐含条款规定；除条例允许外，不得以合约条款排除。',
                 ('买卖', '货物', '隐含条款', '品质', '采购'),
                 source='香港法例第26章《貨品售賣條例》',
                 source_url='https://www.elegislation.gov.hk/hk/cap26',
                 jurisdiction='hongkong', contract_types=('procurement',)),
    LegalArticle('hk-cap26-s15', '香港法例第26章第15条', '适销品质',
                 '货物须适合一般用途、外观及表面瑕疵可接受、安全耐用；具体标准受交易习惯和价格等因素影响。',
                 ('品质', '适销', '货物', '验收', '采购'),
                 source='香港法例第26章《貨品售賣條例》',
                 source_url='https://www.elegislation.gov.hk/hk/cap26',
                 jurisdiction='hongkong', contract_types=('procurement',)),
    LegalArticle('hk-cap26-s16', '香港法例第26章第16条', '用途适用性',
                 '如买方明示或默示让卖方知悉货物所需用途，卖方提供的货物须合理适合该用途，即使该用途并非货物通常用途。',
                 ('用途', '适用性', '货物', '采购'),
                 source='香港法例第26章《貨品售賣條例》',
                 source_url='https://www.elegislation.gov.hk/hk/cap26',
                 jurisdiction='hongkong', contract_types=('procurement',)),
    # 中国香港：雇佣
    LegalArticle('hk-cap57-s6', '香港法例第57章第6条', '终止雇佣的通知期',
                 '雇佣合约可由任何一方以口头或书面通知终止；通知期按合约约定，连续合约不少于7天；按月续期且合约未约定通知期的，不少于1个月。',
                 ('雇佣', '通知期', '解雇', '终止', '辞职', '连续合约'),
                 source='香港法例第57章《僱傭條例》',
                 source_url='https://www.elegislation.gov.hk/hk/cap57',
                 jurisdiction='hongkong', contract_types=('labor',)),
    LegalArticle('hk-cap57-s7', '香港法例第57章第7条', '代通知金',
                 '雇主或雇员可按通知期相应的工资支付代通知金，以终止雇佣合约；代通知金按通知期内应得工资计算。',
                 ('代通知金', '通知期', '解雇', '终止'),
                 source='香港法例第57章《僱傭條例》',
                 source_url='https://www.elegislation.gov.hk/hk/cap57',
                 jurisdiction='hongkong', contract_types=('labor',)),
    LegalArticle('hk-cap57-s9', '香港法例第57章第9条', '雇主即时解雇的限制',
                 '雇主只可在雇员故意不服从合法合理命令、行为不当、欺诈或不诚实、惯常疏忽等法定情况下，无通知或代通知金解雇；并非可随时无理由即时解雇。',
                 ('即时解雇', '无通知', '解雇', '严重过失', '行为不当'),
                 source='香港法例第57章《僱傭條例》',
                 source_url='https://www.elegislation.gov.hk/hk/cap57',
                 jurisdiction='hongkong', contract_types=('labor',)),
    LegalArticle('hk-cap57-s32', '香港法例第57章第32条', '扣除工资的限制',
                 '除条例允许的情况外，雇主不得从工资或其他应付雇员款项中扣除；扣除总额一般不得超过该工资期应付工资的一半，条例另有例外。',
                 ('扣工资', '工资扣除', '罚款', '押金', '按金'),
                 source='香港法例第57章《僱傭條例》',
                 source_url='https://www.elegislation.gov.hk/hk/cap57',
                 jurisdiction='hongkong', contract_types=('labor',)),
    LegalArticle('hk-cap57-s15', '香港法例第57章第15条', '怀孕雇员的解雇保护',
                 '怀孕雇员发出怀孕通知后，雇主不得在怀孕至产假结束期间非依第9条解雇；试用期等特定情形有例外，需按条文判断。',
                 ('怀孕', '产假', '解雇'),
                 source='香港法例第57章《僱傭條例》',
                 source_url='https://www.elegislation.gov.hk/hk/cap57',
                 jurisdiction='hongkong', contract_types=('labor',)),
    LegalArticle('hk-cap57-s31b', '香港法例第57章第31B条', '遣散费',
                 '连续受雇不少于24个月的雇员，因裁员、停工等法定情况被解雇，可按条例获遣散费；具体计算和资格以条文为准。',
                 ('遣散费', '裁员', '停工', '解雇', '长期服务'),
                 source='香港法例第57章《僱傭條例》',
                 source_url='https://www.elegislation.gov.hk/hk/cap57',
                 jurisdiction='hongkong', contract_types=('labor',)),
    LegalArticle('hk-cap57-s33', '香港法例第57章第33条', '疾病津贴',
                 '连续受雇满1个月的雇员，在符合病假和证明要求的情况下可获疾病津贴；津贴按条例规定的工资比例和条件计算。',
                 ('病假', '疾病津贴', '有薪病假'),
                 source='香港法例第57章《僱傭條例》',
                 source_url='https://www.elegislation.gov.hk/hk/cap57',
                 jurisdiction='hongkong', contract_types=('labor',)),
    LegalArticle('hk-cap485-mpf-note', '香港法例第485章（强积金制度说明）', '强积金供款义务',
                 '除获豁免人士外，雇主须为有关雇员登记强积金计划并作出雇主供款；雇员亦须作出雇员供款。具体豁免、供款期和计算以条例及计划文件为准。',
                 ('强积金', '強積金', 'MPF', '供款', '雇主供款', '雇员供款'),
                 source='香港法例第485章《強制性公積金計劃條例》',
                 source_url='https://www.elegislation.gov.hk/hk/cap485',
                 jurisdiction='hongkong', contract_types=('labor',)),
    LegalArticle('hk-cap163-s24', '香港法例第163章第24条', '放债利率上限',
                 '任何人以超过年化48%的实际利率放债或提出放债，即属犯罪；超过该利率的还款协议/利息/担保不可强制执行。',
                 ('利息', '利率', '高利', '放债', '贷款', '服务费'),
                 source='香港法例第163章《放債人條例》',
                 source_url='https://www.elegislation.gov.hk/hk/cap163',
                 jurisdiction='hongkong', contract_types=('loan',)),
    LegalArticle('hk-cap163-s25', '香港法例第163章第25条', '重新审议敲诈性交易',
                 '如法庭认为贷款交易属敲诈性，可重新审议交易并按公平原则调整双方权利义务。',
                 ('敲诈', '不公平', '利息', '贷款', '放债'),
                 source='香港法例第163章《放債人條例》',
                 source_url='https://www.elegislation.gov.hk/hk/cap163',
                 jurisdiction='hongkong', contract_types=('loan',)),
    LegalArticle('hk-cap163-s19', '香港法例第163章第19条', '放债人提供资料义务',
                 '借款人可书面要求放债人提供贷款协议资料、还款安排和已收/应收款项等资料。',
                 ('贷款', '还款', '资料', '放债', '利息'),
                 source='香港法例第163章《放債人條例》',
                 source_url='https://www.elegislation.gov.hk/hk/cap163',
                 jurisdiction='hongkong', contract_types=('loan',)),
    LegalArticle('hk-cap609-s19', '香港法例第609章第19条', '仲裁协议定义与形式',
                 '《仲裁条例》采用联合国示范法第7条，仲裁协议可以是合同中的仲裁条款或独立协议，须以书面形式作出。',
                 ('仲裁', '仲裁协议', '争议解决', '书面'),
                 source='香港法例第609章《仲裁條例》',
                 source_url='https://www.elegislation.gov.hk/hk/cap609',
                 jurisdiction='hongkong', contract_types=('dispute',)),
    LegalArticle('hk-cap609-s5', '香港法例第609章第5条', '仲裁条例适用范围',
                 '仲裁地点在香港的仲裁适用《仲裁条例》；仲裁协议可约定香港或外地仲裁，具体适用部分取决于仲裁地。',
                 ('仲裁', '仲裁地', '争议解决', '管辖'),
                 source='香港法例第609章《仲裁條例》',
                 source_url='https://www.elegislation.gov.hk/hk/cap609',
                 jurisdiction='hongkong', contract_types=('dispute',)),
    LegalArticle('hk-cap362-s7', '香港法例第362章第7条', '虚假商品说明',
                 '在营商过程中将虚假商品说明应用于货品，或供应/要约供应带有虚假商品说明的货品，可能构成罪行。',
                 ('虚假宣传', '商品说明', '描述', '电商', '消费者'),
                 source='香港法例第362章《商品說明條例》',
                 source_url='https://www.elegislation.gov.hk/hk/cap362',
                 jurisdiction='hongkong', contract_types=('ecommerce', 'consumer')),
    LegalArticle('hk-franchise-note', '香港：无专门特许经营法例', '加盟合同的法律框架',
                 '香港没有专门的加盟披露/冷静期法例；加盟合同主要受一般合约法、以及在不合情理情况下可能适用的《不合情理合约条例》等约束，需逐案判断。',
                 ('加盟', '特许经营', '加盟费', '保证金', '冷静期', '信息披露', '不合情理'),
                 source='香港：无专门特许经营法例（参考第458章）',
                 source_url='https://www.elegislation.gov.hk/hk/cap458',
                 jurisdiction='hongkong', contract_types=('franchise',)),
)


def _tokens(text: str) -> List[str]:
    text = text or ''
    words = re.findall(r'[\u4e00-\u9fff]{2,8}', text)
    return words


def retrieve_legal_basis(
    query: str,
    limit: int = 2,
    jurisdiction: str = 'mainland',
    contract_type: str | None = None,
) -> List[dict]:
    """按法域 + 合同类型 + 关键词重合度返回条文要旨；没有匹配则返回空。"""
    query = query or ''
    jurisdiction = (jurisdiction or 'mainland').strip().lower()
    specific_markers = (
        '押金', '按金', '扣除', '违约金', '维修', '解除', '续租', '加租',
        '退款', '退费', '手续费', '验收', '尾款', '付款', '工资', '加班',
        '社保', '竞业', '试用期', '罚款', '质保', '保修',
    )
    specific = any(marker in query for marker in specific_markers)
    scored = []
    for article in ARTICLES:
        if article.jurisdiction != jurisdiction:
            continue
        if contract_type and contract_type != 'rental':
            # 内地《民法典》第7xx条与香港第7章是租赁专门规则，不能用于其他合同类型
            if article.article_id.startswith('art7') or article.article_id.startswith('hk-cap7-'):
                continue
        if article.is_definition and specific:
            # 定义条款不能单独支撑具体风险结论；避免把“第2条定义”当作押金/违约金依据
            continue
        if contract_type and contract_type not in article.contract_types and 'general' not in article.contract_types:
            continue
        hits = [kw for kw in article.keywords if kw in query]
        if not hits:
            continue
        # 标题/摘要中的词也作为弱匹配
        extra = sum(1 for token in _tokens(query) if token in article.summary)
        score = len(hits) * 3 + extra
        scored.append((score, article, hits))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {**article.to_dict(), 'matched_keywords': hits}
        for _, article, hits in scored[:limit]
    ]


__all__ = ['ARTICLES', 'LegalArticle', 'retrieve_legal_basis']

