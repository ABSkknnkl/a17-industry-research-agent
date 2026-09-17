/**
 * 基于后端真实流水线 run b3f5732f-e86a-4a7e-a5a5-fede9c3af8f3 的演示数据抽取。
 * 数据来源：同花顺问财 SkillHub 宏观/财务 + LLM（Agent2/4）结论与章节。
 * 装机量/三家份额结构化缺口按后端缺口披露，份额数字为公开口径补充，已标注。
 */
import type {
  ArtifactItem,
  ChapterItem,
  ChartItem,
  ClaimItem,
  EvidenceItem,
  ReportSettings,
  RiskItem,
} from '../../api/types'
import { buildFusedReportHtml } from './fusedReportHtml'

export const REAL_RUN_ID = 'b3f5732f-e86a-4a7e-a5a5-fede9c3af8f3'
export const DEMO_RUN_ID = 'mock-amd-001'
export const DEMO_PROJECT_ID = 'proj-battery-real'
export const DEMO_TITLE = '动力电池行业 2023-2026 研究（真实流水线）'
export const FIXED_NOW = '2026-01-15T10:30:00.000Z'
export const FIXED_CREATED_AT = '2026-01-15T09:00:00.000Z'
export const DEMO_BANNER =
  '部分数据来自后端真实取数与大模型分析；装机/份额缺口已标注，不代表投资建议'
/**
 * fixture 版本：改动**任何 fixture 内容**（尤其是 cloneArtifacts 的产物正文）都必须递增。
 *
 * prototypeRun 会把整个 state（含 artifacts[].content）持久化到 localStorage，
 * hydrate() 只在版本不一致时丢弃旧缓存。不递增的话，改了产物内容但浏览器里
 * 仍是旧缓存 —— 表现为「代码改了、页面没变」。
 * v1 → v2：report_html 产物由 <pre>markdown</pre> 改为生成完整的融合报告 HTML。
 */
export const FIXTURE_VERSION = 'battery-real-v2'
export const MOCK_DELAY_MS = 400
export const CHART_REGEN_MS = 800

export const DEMO_QUESTIONS = [
  '动力电池行业2023年至2026年装机量及增速变化趋势如何？',
  '宁德时代、比亚迪、中创新航动力电池装机量市场份额对比如何？',
  '碳酸锂价格2023年以来走势及其对电池成本的影响？',
  '动力电池行业主要企业研发投入规模及占营业收入比重变化？',
]

export const defaultReportSettings: ReportSettings = {
  tone: 'professional',
  depth: 'standard',
  chart_density: 'balanced',
  formats: ['markdown', 'html', 'pdf'],
  summary_length: 'standard',
}

export const REAL_SERIES = {
  lithiumSpotWan: [
    ['2023-12-14', 10.24],
    ['2023-12-15', 10.24],
    ['2023-12-18', 10.14],
    ['2023-12-19', 9.84],
    ['2023-12-20', 9.74],
    ['2023-12-21', 9.74],
    ['2023-12-22', 9.74],
    ['2023-12-25', 9.74],
    ['2023-12-26', 9.58],
    ['2023-12-27', 9.54],
    ['2023-12-28', 9.4],
    ['2023-12-29', 9.4],
    ['2026-08-31', 15.4],
    ['2026-09-01', 15.4],
    ['2026-09-02', 15.1],
    ['2026-09-03', 15.1],
    ['2026-09-04', 14.8],
    ['2026-09-07', 14.0],
    ['2026-09-08', 14.0],
    ['2026-09-09', 13.8],
    ['2026-09-10', 13.8],
    ['2026-09-11', 13.3],
    ['2026-09-14', 13.0],
    ['2026-09-15', 12.8],
  ],
  batteryOutput2023: [
    ['2023-01-31', 28169.2],
    ['2023-02-28', 41450.5],
    ['2023-03-31', 51186],
    ['2023-04-30', 46958.3],
    ['2023-05-31', 56556.1],
    ['2023-06-30', 60116.1],
    ['2023-07-31', 60995.8],
    ['2023-08-31', 73345],
    ['2023-09-30', 77400],
    ['2023-10-31', 77300],
    ['2023-11-30', 87700],
    ['2023-12-31', 77700],
  ],
  batteryOutput2526: [
    ['2025-09-30', 151200],
    ['2025-10-31', 170600],
    ['2025-11-30', 176300],
    ['2025-12-31', 201700],
    ['2026-01-31', 168000],
    ['2026-02-28', 141600],
    ['2026-03-31', 177700],
    ['2026-04-30', 183900],
    ['2026-05-31', 191700],
    ['2026-06-30', 206000],
    ['2026-07-31', 218000],
    ['2026-08-31', 237000],
  ],
  ppi: [
    ['2025-12-31', -1.9],
    ['2026-01-31', -1.4],
    ['2026-02-28', -0.9],
    ['2026-03-31', 0.5],
    ['2026-04-30', 2.8],
    ['2026-05-31', 3.9],
    ['2026-06-30', 4.1],
    ['2026-07-31', 3.5],
    ['2026-08-31', 3.8],
  ],
  rd2025: [
    { scope: '宁德时代', revenue: 4237.02, np: 722.01, rd: 221.47, rdRatio: 5.23 },
    { scope: '比亚迪', revenue: 8039.65, np: 326.19, rd: 634.41, rdRatio: 7.89 },
    { scope: '亿纬锂能', revenue: 614.7, np: 41.34, rd: 34.35, rdRatio: 5.59 },
    { scope: '国轩高科', revenue: 450.7, np: null, rd: 33.65, rdRatio: 7.47 },
  ],
}

export type RealPoint = [string, number]
export const LITHIUM_SPOT = REAL_SERIES.lithiumSpotWan as RealPoint[]
export const BATTERY_OUT_2023 = REAL_SERIES.batteryOutput2023 as RealPoint[]
export const BATTERY_OUT_2526 = REAL_SERIES.batteryOutput2526 as RealPoint[]
export const PPI_SERIES = REAL_SERIES.ppi as RealPoint[]

export const REAL_CLAIMS_RAW = [
  {
    claim_id: 'C-COMP-001',
    claim_type: 'fact',
    text: '2025财年（截至2025-12-31，未经审计）宁德时代营业收入4237.02亿元，同比增长17.04%；归母净利润722.01亿元，归母净利率17.04%。比亚迪营业收入8039.65亿元，同比增长3.46%；归母净利润326.19亿元，归母净利率4.06%。',
    evidence_ids: [
      'E-7c4936a75031f54b',
      'E-129e6bfed9481264',
      'E-872b4c334afefd0e',
      'E-ffab4b2fb603d882',
      'E-331f2cb93530fe04',
      'E-f96fb4f031e4ca99',
    ],
    counter_evidence_ids: [],
    confidence: 'high',
    uncertainty:
      '数据为未经审计的B级终端数据，且公告日（2026-01-15）晚于研究时点（2026-01-15），存在前视偏差风险，需以正式年报复核。',
    status: 'pending_review',
  },
  {
    claim_id: 'C-COMP-002',
    claim_type: 'inference',
    text: '宁德时代与比亚迪的净利率差异（17.04% vs 4.06%）反映两家公司商业模式差异：宁德时代作为动力电池供应商，产品附加值较高；比亚迪作为垂直整合的汽车制造商，收入规模大但利润被整车及零部件业务摊薄。',
    evidence_ids: [
      'E-7c4936a75031f54b',
      'E-872b4c334afefd0e',
      'E-ffab4b2fb603d882',
      'E-f96fb4f031e4ca99',
    ],
    counter_evidence_ids: [],
    confidence: 'medium',
    uncertainty:
      '净利率差异可能还受产品结构、补贴、非经常性损益等因素影响，需进一步拆解分部数据验证。',
    status: 'pending_review',
  },
  {
    claim_id: 'C-COMP-003',
    claim_type: 'fact',
    text: '2025财年（截至2025-12-31，未经审计）宁德时代研发支出221.47亿元，比亚迪研发支出634.41亿元。',
    evidence_ids: ['E-f46794167ff5ec5a', 'E-ee81abbc475d31ae'],
    counter_evidence_ids: [],
    confidence: 'high',
    uncertainty:
      '研发支出数据为B级终端数据，未经审计，且未提供研发支出资本化率，跨公司比较需注意口径差异。',
    status: 'pending_review',
  },
  {
    claim_id: 'C-COMP-004',
    claim_type: 'inference',
    text: '比亚迪研发支出绝对额显著高于宁德时代（634.41亿 vs 221.47亿），但考虑到比亚迪收入规模约为宁德时代的1.9倍，研发强度（研发/收入）差异较小（约7.9% vs 5.2%），两者均保持较高研发投入以维持技术竞争力。',
    evidence_ids: [
      'E-ee81abbc475d31ae',
      'E-f46794167ff5ec5a',
      'E-ffab4b2fb603d882',
      'E-7c4936a75031f54b',
    ],
    counter_evidence_ids: [],
    confidence: 'medium',
    uncertainty: '研发强度为推算值，基于B级数据，未考虑研发资本化差异。',
    status: 'pending_review',
  },
  {
    claim_id: 'C-MACRO-001',
    claim_type: 'fact',
    text: '中国PPI当月同比自2025年12月的-1.9%持续回升，2026年1月至6月分别为-1.4%、-0.9%、0.5%、2.8%、3.9%、4.1%，2026年7月和8月分别为3.5%和3.8%，显示工业品价格进入上行通道。',
    evidence_ids: [
      'E-a775271987d266a8',
      'E-1d1e99c327f56b43',
      'E-381cc1ccc4cf1c24',
      'E-9e6e7a90bb73121c',
      'E-2e2fa378573289a1',
      'E-76e0838543563f14',
      'E-fbcf1d58bc5a2156',
      'E-6d9e217d91a98809',
      'E-6427a24814b1c99c',
    ],
    counter_evidence_ids: [],
    confidence: 'high',
    uncertainty:
      'PPI数据为B级宏观数据，统计口径为当月同比，未提供环比数据，且部分数据点（2026年7-8月）晚于研究时点（2026-01-15），存在前视偏差风险。',
    status: 'pending_review',
  },
  {
    claim_id: 'C-MACRO-002',
    claim_type: 'inference',
    text: 'PPI同比转正并加速上行（2026年3月起转正，6月达4.1%），可能反映上游资源品及工业品需求回暖或供给收缩，对动力电池行业而言，若上游原材料（如碳酸锂）价格同步上涨，将推升电池制造成本，压缩中游电池企业利润空间。',
    evidence_ids: [
      'E-9e6e7a90bb73121c',
      'E-2e2fa378573289a1',
      'E-76e0838543563f14',
      'E-fbcf1d58bc5a2156',
    ],
    counter_evidence_ids: [],
    confidence: 'low',
    uncertainty:
      'PPI与碳酸锂价格的相关性未直接验证，且缺乏碳酸锂价格直接数据，此推断为逻辑推演，需补充碳酸锂价格数据验证。',
    status: 'pending_review',
  },
  {
    claim_id: 'C-IND-001',
    claim_type: 'fact',
    text: '宁德时代2026年一季度国内动力电池市占率达47.7%，同比提升3.4个百分点（来源：同花顺产业链解读文档，C级证据，仅作定性参考）。',
    evidence_ids: ['E-c516b3ef2bd3ebd3'],
    counter_evidence_ids: [],
    confidence: 'low',
    uncertainty:
      '该数据来自C级文档证据，未提供原始数据来源，且研究时点（2026-01-15）早于2026年一季度，存在前视偏差，需以权威机构数据复核。',
    status: 'pending_review',
  },
  {
    claim_id: 'C-IND-002',
    claim_type: 'inference',
    text: '宁德时代国内动力电池市占率接近50%，显示行业集中度较高，龙头地位稳固，但比亚迪、中创新航等竞争对手的份额数据缺失，无法进行完整对比。',
    evidence_ids: ['E-c516b3ef2bd3ebd3'],
    counter_evidence_ids: [],
    confidence: 'low',
    uncertainty: '仅依赖单一C级证据，且缺乏竞争对手数据，结论强度不足。',
    status: 'pending_review',
  },
]
export const REAL_CHAPTERS_RAW = [
  {
    chapter_id: 'CH-01',
    title: '行业定义与研究基础',
    order: 1,
    sections: [
      {
        section_id: 'SEC-01-01',
        title: '行业定义、研究边界与证券范围',
        paragraphs: [
          {
            paragraph_id: 'P-01-01-01',
            section_id: 'SEC-01-01',
            text: "本章研究范围为中国A股动力电池行业上市公司，证券类型为股票，计价货币为人民币。行业分类采用同花顺'电力设备-电池-锂电池'标准，相关产品包括动力电池、磷酸铁锂电池、三元电池。",
            kind: 'analysis',
          },
          {
            paragraph_id: 'P-01-01-02',
            section_id: 'SEC-01-01',
            text: '主要对比对象为宁德时代与比亚迪，两者均以人民币计价并采用中国会计准则，财年一致（截至2025-12-31）。但业务结构不同：宁德时代为动力电池供应商，比亚迪为垂直整合的汽车制造商，因此净利率不可直接类比。',
            kind: 'analysis',
          },
        ],
      },
      {
        section_id: 'SEC-01-02',
        title: '数据口径、研究时点与分析方法',
        paragraphs: [
          {
            paragraph_id: 'P-01-02-01',
            section_id: 'SEC-01-02',
            text: '研究时点为2026-01-15，但宁德时代与比亚迪2025财年财务数据公告日（2026-01-15）晚于研究时点，且为未经审计的B级终端数据，存在前视偏差风险，需以正式年报复核。',
            kind: 'analysis',
          },
          {
            paragraph_id: 'P-01-02-02',
            section_id: 'SEC-01-02',
            text: '动力电池装机量、市场份额及碳酸锂价格等关键数据缺失，行业整体趋势判断受限。现有市占率数据（宁德时代2026年一季度47.7%）为C级证据，且晚于研究时点，仅作定性参考。',
            kind: 'analysis',
          },
        ],
      },
    ],
  },
  {
    chapter_id: 'CH-02',
    title: '市场规模与成长性',
    order: 2,
    sections: [
      {
        section_id: 'SEC-02-01',
        title: '市场规模与历史增长趋势',
        paragraphs: [
          {
            paragraph_id: 'P-02-01-01',
            section_id: 'SEC-02-01',
            text: '当前可用证据不足以对“市场规模与历史增长趋势”形成可靠事实判断，本节保留研究位置，待补充数据后复核。',
            kind: 'methodology',
          },
          {
            paragraph_id: 'P-02-01-02',
            section_id: 'SEC-02-01',
            text: '宁德时代2025年营业收入4237.02亿元，同比增长17.04%；归母净利润722.01亿元，归母净利率17.04%。比亚迪2025年营业收入8039.65亿元，同比增长3.46%；归母净利润326.19亿元，归母净利率4.06%。宁德时代营收增速显著高于比亚迪，但两者业务结构不同，不可直接比较。',
            kind: 'analysis',
          },
          {
            paragraph_id: 'P-02-01-03',
            section_id: 'SEC-02-01',
            text: '上述财务数据为未经审计的B级终端数据，且公告日晚于研究时点（2026-01-15），存在前视偏差风险，需以正式年报复核。',
            kind: 'analysis',
          },
        ],
      },
      {
        section_id: 'SEC-02-02',
        title: '需求驱动因素与细分市场变化',
        paragraphs: [
          {
            paragraph_id: 'P-02-02-01',
            section_id: 'SEC-02-02',
            text: '需求驱动因素方面，新能源汽车渗透率提升与政策支持是主要动力，但缺乏具体数据支撑。宁德时代2026年一季度国内市占率47.7%（C级证据），显示龙头地位稳固，但缺乏比亚迪、中创新航份额数据，无法完成三方对比。',
            kind: 'analysis',
          },
          {
            paragraph_id: 'P-02-02-02',
            section_id: 'SEC-02-02',
            text: '亿纬锂能与国轩高科2026年上半年归母净利润分别同比增长105.66%和278.05%（C级证据），可能反映二线电池企业盈利能力改善，但基数效应和C级证据质量需谨慎对待。',
            kind: 'analysis',
          },
          {
            paragraph_id: 'P-02-02-03',
            section_id: 'SEC-02-02',
            text: '上述二线企业数据为C级文档证据，且晚于研究时点，存在前视偏差，仅作定性参考，不参与计算。',
            kind: 'analysis',
          },
        ],
      },
    ],
  },
  {
    chapter_id: 'CH-03',
    title: '产业链与利润分配',
    order: 3,
    sections: [
      {
        section_id: 'SEC-03-01',
        title: '上游资源、原材料与关键供应环节',
        paragraphs: [
          {
            paragraph_id: 'P-03-01-01',
            section_id: 'SEC-03-01',
            text: '当前可用证据不足以对“上游资源、原材料与关键供应环节”形成可靠事实判断，本节保留研究位置，待补充数据后复核。',
            kind: 'methodology',
          },
          {
            paragraph_id: 'P-03-01-02',
            section_id: 'SEC-03-01',
            text: '湖南裕能布局锂电池回收业务，反映产业链向回收环节延伸的趋势。湖南裕能2023年半年报显示设立湖南裕能循环开展锂电池回收业务，但该业务规模及盈利贡献尚不明确。该结论基于单一C级证据，置信度较低，需进一步验证。',
            kind: 'analysis',
          },
          {
            paragraph_id: 'P-03-01-03',
            section_id: 'SEC-03-01',
            text: '当前可用证据不足以对“上游资源、原材料与关键供应环节”形成可靠事实判断，本节保留研究位置，待补充数据后复核。',
            kind: 'methodology',
          },
        ],
      },
      {
        section_id: 'SEC-03-02',
        title: '中游核心产品、制造与服务环节',
        paragraphs: [
          {
            paragraph_id: 'P-03-02-01',
            section_id: 'SEC-03-02',
            text: '宁德时代与行业相关系数高达92.12%，可作为行业景气度的代理指标。该相关系数表明其股价走势与行业高度同步，但证据等级为C级，计算方法与样本区间未披露，且相关系数不代表因果关系。',
            kind: 'analysis',
          },
          {
            paragraph_id: 'P-03-02-02',
            section_id: 'SEC-03-02',
            text: '亿纬锂能与行业相关系数为64.05%，低于宁德时代，可能反映其业务结构或市场预期与行业存在差异。该差异可能源于产品结构、客户群体或市场定位的不同，但缺乏具体数据支持，仅作定性参考。',
            kind: 'analysis',
          },
        ],
      },
    ],
  },
  {
    chapter_id: 'CH-04',
    title: '竞争格局',
    order: 4,
    sections: [
      {
        section_id: 'SEC-04-01',
        title: '市场结构、集中度与竞争阶段',
        paragraphs: [
          {
            paragraph_id: 'P-04-01-01',
            section_id: 'SEC-04-01',
            text: '宁德时代2026年一季度国内动力电池市占率达47.7%，同比提升3.4个百分点，显示行业集中度较高，龙头地位稳固。该数据来自同花顺产业链解读文档，属于C级证据，未提供原始数据来源，且研究时点早于2026年一季度，存在前视偏差，需以权威机构数据复核。',
            kind: 'analysis',
          },
          {
            paragraph_id: 'P-04-01-02',
            section_id: 'SEC-04-01',
            text: '宁德时代与比亚迪的净利率差异（17.04% vs 4.06%）反映两家公司商业模式差异：宁德时代作为动力电池供应商，产品附加值较高；比亚迪作为垂直整合的汽车制造商，收入规模大但利润被整车及零部件业务摊薄。该差异可能还受产品结构、补贴、非经常性损益等因素影响，需进一步拆解分部数据验证。',
            kind: 'analysis',
          },
          {
            paragraph_id: 'P-04-01-03',
            section_id: 'SEC-04-01',
            text: '宁德时代国内动力电池市占率接近50%，显示行业集中度较高，龙头地位稳固，但比亚迪、中创新航等竞争对手的份额数据缺失，无法进行完整对比。该结论仅依赖单一C级证据，且缺乏竞争对手数据，结论强度不足。',
            kind: 'analysis',
          },
        ],
      },
      {
        section_id: 'SEC-04-02',
        title: '主要参与者及其竞争位置',
        paragraphs: [
          {
            paragraph_id: 'P-04-02-01',
            section_id: 'SEC-04-02',
            text: '2025财年（截至2025-12-31，未经审计）宁德时代营业收入4237.02亿元，同比增长17.04%；归母净利润722.01亿元，归母净利率17.04%。比亚迪营业收入8039.65亿元，同比增长3.46%；归母净利润326.19亿元，归母净利率4.06%。数据为未经审计的B级终端数据，且公告日晚于研究时点，存在前视偏差风险，需以正式年报复核。',
            kind: 'analysis',
          },
          {
            paragraph_id: 'P-04-02-02',
            section_id: 'SEC-04-02',
            text: '宁德时代与比亚迪的净利率差异（17.04% vs 4.06%）反映两家公司商业模式差异：宁德时代作为动力电池供应商，产品附加值较高；比亚迪作为垂直整合的汽车制造商，收入规模大但利润被整车及零部件业务摊薄。该差异可能还受产品结构、补贴、非经常性损益等因素影响，需进一步拆解分部数据验证。',
            kind: 'analysis',
          },
        ],
      },
    ],
  },
  {
    chapter_id: 'CH-05',
    title: '财务质量与估值参照',
    order: 5,
    sections: [
      {
        section_id: 'SEC-05-01',
        title: '收入、利润与盈利能力',
        paragraphs: [
          {
            paragraph_id: 'P-05-01-01',
            section_id: 'SEC-05-01',
            text: '宁德时代2025财年营业收入4237.02亿元，同比增长17.04%；归母净利润722.01亿元，归母净利率17.04%。该数据为未经审计的B级终端数据，公告日与研究时点相同，存在前视偏差风险，需以正式年报复核。',
            kind: 'analysis',
          },
          {
            paragraph_id: 'P-05-01-02',
            section_id: 'SEC-05-01',
            text: '比亚迪2025财年营业收入8039.65亿元，同比增长3.46%；归母净利润326.19亿元，归母净利率4.06%。其收入规模约为宁德时代的1.9倍，但净利率显著偏低，反映垂直整合模式下利润被整车及零部件业务摊薄。',
            kind: 'analysis',
          },
          {
            paragraph_id: 'P-05-01-03',
            section_id: 'SEC-05-01',
            text: '宁德时代与比亚迪的净利率差异（17.04% vs 4.06%）反映商业模式差异：前者作为动力电池供应商，产品附加值较高；后者作为垂直整合的汽车制造商，收入规模大但利润被整车及零部件业务摊薄。该差异可能还受产品结构、补贴、非经常性损益等因素影响，需进一步拆解分部数据验证。',
            kind: 'analysis',
          },
        ],
      },
      {
        section_id: 'SEC-05-02',
        title: '现金流、资产负债与财务质量',
        paragraphs: [
          {
            paragraph_id: 'P-05-02-01',
            section_id: 'SEC-05-02',
            text: '当前可用证据不足以对“现金流、资产负债与财务质量”形成可靠事实判断，本节保留研究位置，待补充数据后复核。',
            kind: 'methodology',
          },
          {
            paragraph_id: 'P-05-02-02',
            section_id: 'SEC-05-02',
            text: '研发投入方面，宁德时代2025财年研发支出221.47亿元，比亚迪研发支出634.41亿元。比亚迪研发支出绝对额显著高于宁德时代，但考虑到其收入规模约为宁德时代的1.9倍，研发强度（研发/收入）差异较小（约7.9% vs 5.2%），两者均保持较高研发投入以维持技术竞争力。该研发强度为推算值，基于B级数据，未考虑研发资本化差异。',
            kind: 'analysis',
          },
        ],
      },
    ],
  },
  {
    chapter_id: 'CH-06',
    title: '宏观、政策与技术催化',
    order: 6,
    sections: [
      {
        section_id: 'SEC-06-01',
        title: '宏观经济变量与行业传导路径',
        paragraphs: [
          {
            paragraph_id: 'P-06-01-01',
            section_id: 'SEC-06-01',
            text: '中国PPI当月同比自2025年12月的-1.9%持续回升，2026年6月达4.1%，显示工业品价格进入上行通道。该数据为宏观背景参考，与动力电池行业成本的相关性未经验证。',
            kind: 'analysis',
          },
          {
            paragraph_id: 'P-06-01-02',
            section_id: 'SEC-06-01',
            text: 'PPI同比转正并加速上行，可能反映上游资源品及工业品需求回暖或供给收缩。若上游原材料价格同步上涨，将推升电池制造成本，压缩中游电池企业利润空间。该推断为逻辑推演，PPI与碳酸锂价格的相关性未直接验证。',
            kind: 'analysis',
          },
        ],
      },
      {
        section_id: 'SEC-06-02',
        title: '政策、监管与合规环境',
        paragraphs: [
          {
            paragraph_id: 'P-06-02-01',
            section_id: 'SEC-06-02',
            text: '本节旨在说明政策时点、范围和可能影响。当前输入中未包含直接针对动力电池行业的政策、监管或合规数据，因此无法展开具体分析。',
            kind: 'transition',
          },
        ],
      },
    ],
  },
  {
    chapter_id: 'CH-07',
    title: '情景、风险与研究结论',
    order: 7,
    sections: [
      {
        section_id: 'SEC-07-01',
        title: '基准、乐观和悲观三种情景',
        paragraphs: [
          {
            paragraph_id: 'P-07-01-01',
            section_id: 'SEC-07-01',
            text: '基准情景假设2025年财务数据仅作参考，PPI同比在2026年1-8月波动于-1.9%至4.1%之间，反映宏观价格环境，但未直接对应动力电池行业价格。该情景下，若PPI持续为正且上行，可能推升上游原材料成本，压缩中游电池企业利润空间；但PPI与碳酸锂价格的相关性未直接验证，此推断为逻辑推演。',
            kind: 'analysis',
          },
          {
            paragraph_id: 'P-07-01-02',
            section_id: 'SEC-07-01',
            text: '乐观情景假设宁德时代2026年一季度国内市占率47.7%（同比提升3.4个百分点）的表述可信，且行业集中度进一步提升。该情景下，若碳酸锂价格企稳回升且电池企业成功将成本转嫁下游，叠加需求端韧性，头部企业盈利有望改善。但该市占率数据来自C级文档证据，且研究时点早于2026年一季度，存在前视偏差，需以权威机构数据复核。',
            kind: 'analysis',
          },
          {
            paragraph_id: 'P-07-01-03',
            section_id: 'SEC-07-01',
            text: '悲观情景假设碳酸锂价格持续下跌，引发电池价格战，行业毛利率普遍下滑。该情景下，若PPI再度转负，可能反映制造业需求疲软，对动力电池行业需求端构成压力。但当前缺乏碳酸锂价格直接数据，PPI与行业成本的相关性未经验证，该情景的触发条件尚不明确。',
            kind: 'analysis',
          },
        ],
      },
      {
        section_id: 'SEC-07-02',
        title: '核心风险、反证条件与跟踪指标',
        paragraphs: [
          {
            paragraph_id: 'P-07-02-01',
            section_id: 'SEC-07-02',
            text: '核心数据缺失风险是当前分析的主要限制。装机量、市场份额、碳酸锂价格等关键行业数据未获取，导致供需格局、竞争格局和成本传导分析缺乏量化基础，结论置信度受限。该风险直接影响行业趋势判断的可靠性，需从权威机构获取数据以补充。',
            kind: 'risk',
          },
          {
            paragraph_id: 'P-07-02-02',
            section_id: 'SEC-07-02',
            text: '前视偏差风险源于宁德时代、比亚迪2025年年报数据公告日晚于研究时点2026-01-15，且为未审计数据。该风险影响对两家公司盈利能力的对比判断，需在报告中标注数据时效性限制，仅作参考，不用于回测或当前判断。',
            kind: 'risk',
          },
          {
            paragraph_id: 'P-07-02-03',
            section_id: 'SEC-07-02',
            text: '宏观价格波动风险方面，2026年PPI同比数据波动较大（-1.9%至4.1%），若PPI持续为负，可能反映制造业需求疲软，对动力电池行业需求端构成压力。但PPI与行业成本的相关性未经验证，该风险传导路径存在不确定性。',
            kind: 'risk',
          },
        ],
      },
    ],
  },
]

/** 真实后端取到的财务/宏观证据 */
export function cloneEvidence(): EvidenceItem[] {
  const rd = REAL_SERIES.rd2025
  const items: EvidenceItem[] = [
    {
      evidence_id: 'EV-RD-CATL',
      title: '宁德时代 2025 营收/净利/研发（问财财务）',
      source_type: 'company',
      publisher: '同花顺问财 · 财务数据',
      as_of_date: '2025-12-31',
      summary: `营收 ${rd[0]!.revenue} 亿元，同比 +17.04%；归母净利 ${rd[0]!.np} 亿元；研发支出 ${rd[0]!.rd} 亿元，费用率约 ${rd[0]!.rdRatio}%。`,
      url_hint: '真实流水线 · 公司财务',
      status: 'active',
      exclude_reason: null,
    },
    {
      evidence_id: 'EV-RD-BYD',
      title: '比亚迪 2025 营收/净利/研发（问财财务）',
      source_type: 'company',
      publisher: '同花顺问财 · 财务数据',
      as_of_date: '2025-12-31',
      summary: `营收 ${rd[1]!.revenue} 亿元，同比 +3.46%；归母净利 ${rd[1]!.np} 亿元；研发支出 ${rd[1]!.rd} 亿元，费用率约 ${rd[1]!.rdRatio}%（含整车业务）。`,
      url_hint: '真实流水线 · 公司财务',
      status: 'active',
      exclude_reason: null,
    },
    {
      evidence_id: 'EV-RD-EVE',
      title: '亿纬锂能 / 国轩高科 2025 财务与研发',
      source_type: 'company',
      publisher: '同花顺问财 · 财务数据',
      as_of_date: '2025-12-31',
      summary: `亿纬：营收 ${rd[2]!.revenue} 亿、研发 ${rd[2]!.rd} 亿（约 ${rd[2]!.rdRatio}%）；国轩：营收 ${rd[3]!.revenue} 亿、研发 ${rd[3]!.rd} 亿（约 ${rd[3]!.rdRatio}%）。`,
      url_hint: '真实流水线 · 公司财务',
      status: 'active',
      exclude_reason: null,
    },
    {
      evidence_id: 'EV-LI-SPOT',
      title: '工业级碳酸锂现货价（问财宏观，周日点）',
      source_type: 'industry',
      publisher: '同花顺问财 · 宏观数据',
      as_of_date: '2026-09-15',
      summary: `2023-12 中旬约 9.4–10.2 万元/吨；2026-08 末约 15.4 万元/吨，9 月中旬回落至约 12.8 万元/吨。真实序列见图表。`,
      url_hint: '真实流水线 · 宏观价格',
      status: 'active',
      exclude_reason: null,
    },
    {
      evidence_id: 'EV-BATT-OUT',
      title: '动力和其他电池产量：当月值（问财宏观）',
      source_type: 'industry',
      publisher: '同花顺问财 · 宏观数据',
      as_of_date: '2026-08-31',
      summary: `2023 年月度产量约 2.8–8.8 万单位；2025Q4–2026 持续抬升，2026-08 约 23.7 万单位（兆瓦时口径）。可作装机景气代理指标。`,
      url_hint: '真实流水线 · 宏观产量',
      status: 'active',
      exclude_reason: null,
    },
    {
      evidence_id: 'EV-PPI',
      title: 'PPI 当月同比（问财宏观）',
      source_type: 'industry',
      publisher: '同花顺问财 · 宏观数据',
      as_of_date: '2026-08-31',
      summary: '2025-12 至 2026-08：-1.9% → +3.8%，工业品价格进入上行通道。',
      url_hint: '真实流水线 · 宏观',
      status: 'active',
      exclude_reason: null,
    },
    {
      evidence_id: 'EV-CATL-SHARE',
      title: '宁德时代市占率定性表述（研报/溯源）',
      source_type: 'opinion',
      publisher: '问财研报摘要 / 溯源分析',
      as_of_date: '2026-01-15',
      summary:
        '溯源表述：2026 年一季度国内动力电池市占率达 47.7%，同比 +3.4pct。中创新航/比亚迪装机份额无结构化序列（后端缺口）。',
      url_hint: '真实流水线 · 定性材料',
      status: 'active',
      exclude_reason: null,
    },
    {
      evidence_id: 'EV-GAP-INSTALL',
      title: '装机量与三家份额结构化数据缺口',
      source_type: 'industry',
      publisher: '后端 SkillHub 缺口披露',
      as_of_date: '2026-01-15',
      summary:
        'REQ 装机量/中创新航份额：hithink 各通道无权威结构化序列，已列入研究边界未编造。公开口径补充：2024 装机约 548GWh（+41.5%），份额宁德约 43%、比亚迪约 25%、中创新航约 8%。',
      url_hint: '真实流水线 · 缺口 + 公开口径补充',
      status: 'active',
      exclude_reason: null,
    },
  ]
  return items
}

export function cloneClaims(): ClaimItem[] {
  const mapped: ClaimItem[] = REAL_CLAIMS_RAW.map((c) => ({
    claim_id: c.claim_id,
    statement: c.text,
    dimension: c.claim_type === 'fact' ? '事实' : '推断',
    evidence_ids: c.evidence_ids ?? [],
    counter_condition: c.uncertainty || '若上游数据修正或口径变化，本结论需复核。',
    status: 'active',
    reject_reason: null,
  }))
  // 补充四问对应结论（真实缺口 + 公开口径）
  mapped.push({
    claim_id: 'CLM-INSTALL',
    statement:
      '后端未取到权威装机量序列。以电池产量作代理：2023 年月产量约 2.8–8.8 万单位，2026-08 升至约 23.7 万单位，景气度抬升。公开口径 2024 装机约 548GWh（+41.5%）。',
    dimension: '装机规模',
    evidence_ids: ['EV-BATT-OUT', 'EV-GAP-INSTALL'],
    counter_condition: '若权威装机数据可得，应以装机口径重算增速。',
    status: 'active',
    reject_reason: null,
  })
  mapped.push({
    claim_id: 'CLM-SHARE',
    statement:
      '宁德时代 2026Q1 国内市占率 47.7%（定性溯源）。中创新航无结构化份额；公开口径 2024 装机份额约宁德 43%、比亚迪 25%、中创新航 8%。',
    dimension: '竞争格局',
    evidence_ids: ['EV-CATL-SHARE', 'EV-GAP-INSTALL'],
    counter_condition: '若改用出货量口径，头部份额可能变动 1–2pct。',
    status: 'active',
    reject_reason: null,
  })
  mapped.push({
    claim_id: 'CLM-LI',
    statement:
      '工业级碳酸锂现货：2023-12 约 9.4–10.2 万元/吨 → 2026-08 约 15.4 万元/吨 → 2026-09 中旬约 12.8 万元/吨。成本端压力较 2023 年末抬升，与“价格持续单边下行”的旧假设不同。',
    dimension: '成本与价格',
    evidence_ids: ['EV-LI-SPOT', 'EV-PPI'],
    counter_condition: '若现货再度跌破 10 万元/吨并维持一个季度，成本逻辑需重估。',
    status: 'active',
    reject_reason: null,
  })
  mapped.push({
    claim_id: 'CLM-RD',
    statement:
      '2025 研发费用率：宁德约 5.2%、比亚迪约 7.9%（含整车）、亿纬约 5.6%、国轩约 7.5%。比亚迪绝对额最高（634 亿）。',
    dimension: '研发投入',
    evidence_ids: ['EV-RD-CATL', 'EV-RD-BYD', 'EV-RD-EVE'],
    counter_condition: '若资本化政策或分部口径调整，费用率不可比。',
    status: 'active',
    reject_reason: null,
  })
  return mapped
}

function lithiumOption(): Record<string, unknown> {
  const pts = LITHIUM_SPOT
  return {
    title: { text: '工业级碳酸锂现货价（真实，万元/吨）', left: 4, textStyle: { fontSize: 13 } },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: pts.map((p) => p[0]) },
    yAxis: { type: 'value', name: '万元/吨' },
    series: [
      {
        name: '碳酸锂现货',
        type: 'line',
        data: pts.map((p) => p[1]),
        smooth: true,
        itemStyle: { color: '#a8402f' },
        areaStyle: { color: 'rgba(169,133,63,0.12)' },
      },
    ],
  }
}

function outputOption(): Record<string, unknown> {
  const a = BATTERY_OUT_2023
  const b = BATTERY_OUT_2526
  const all = [...a, ...b]
  return {
    title: { text: '动力和其他电池产量：当月值（真实）', left: 4, textStyle: { fontSize: 13 } },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: all.map((p) => p[0].slice(0, 7)) },
    yAxis: { type: 'value', name: '万单位' },
    series: [
      {
        name: '产量',
        type: 'bar',
        data: all.map((p) => p[1]),
        barWidth: 14,
        itemStyle: { color: '#1e3a5c' },
      },
    ],
    // 注释放 footnotes（卡片下方展示），不要放进 graphic 绘图区，避免文字与图表重叠
    footnotes: ['注：2024 年序列后端未返回，作代理景气指标'],
  }
}

function rdOption(): Record<string, unknown> {
  const rd = REAL_SERIES.rd2025
  return {
    title: { text: '主要企业研发费用率 2025（真实推算，%）', left: 4, textStyle: { fontSize: 13 } },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: rd.map((r) => r.scope) },
    yAxis: { type: 'value', name: '%' },
    series: [
      {
        type: 'bar',
        data: rd.map((r) => r.rdRatio),
        barWidth: 28,
        itemStyle: { color: '#a9853f' },
        label: { show: true, position: 'top', formatter: '{c}%' },
      },
    ],
  }
}

function shareOption(): Record<string, unknown> {
  return {
    title: {
      text: '装机份额（公开口径补充，后端无结构化序列）',
      left: 4,
      textStyle: { fontSize: 12 },
    },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 8, right: 16, top: 40, bottom: 8, containLabel: true },
    xAxis: { type: 'value', name: '%', max: 50 },
    yAxis: { type: 'category', data: ['其他', '中创新航', '比亚迪', '宁德时代'] },
    series: [
      {
        type: 'bar',
        data: [24, 8, 25, 43],
        barWidth: 18,
        label: { show: true, position: 'right', formatter: '{c}%' },
        itemStyle: { color: '#76899f' },
      },
    ],
  }
}

const CHAIN_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 260" width="640" height="260">
  <rect width="640" height="260" fill="#fffefb"/>
  <text x="20" y="28" font-size="14" fill="#1e3a5c" font-family="Georgia,serif" font-weight="700">动力电池产业链（结构示意）</text>
  <rect x="24" y="56" width="100" height="40" rx="6" fill="#e4e8ee" stroke="#1e3a5c"/>
  <text x="74" y="80" text-anchor="middle" font-size="12" fill="#1e3a5c">锂资源</text>
  <rect x="144" y="56" width="100" height="40" rx="6" fill="#e4e8ee" stroke="#1e3a5c"/>
  <text x="194" y="80" text-anchor="middle" font-size="12" fill="#1e3a5c">正极材料</text>
  <rect x="264" y="56" width="100" height="40" rx="6" fill="#e4e8ee" stroke="#1e3a5c"/>
  <text x="314" y="80" text-anchor="middle" font-size="12" fill="#1e3a5c">电芯</text>
  <rect x="384" y="56" width="100" height="40" rx="6" fill="#e4e8ee" stroke="#1e3a5c"/>
  <text x="434" y="80" text-anchor="middle" font-size="12" fill="#1e3a5c">PACK</text>
  <rect x="504" y="56" width="100" height="40" rx="6" fill="#f4ecdc" stroke="#a9853f"/>
  <text x="554" y="80" text-anchor="middle" font-size="12" fill="#1e3a5c">整车</text>
  <path d="M124 76 H144" stroke="#a9853f" stroke-width="1.5"/>
  <path d="M244 76 H264" stroke="#a9853f" stroke-width="1.5"/>
  <path d="M364 76 H384" stroke="#a9853f" stroke-width="1.5"/>
  <path d="M484 76 H504" stroke="#a9853f" stroke-width="1.5"/>
  <text x="24" y="130" font-size="12" fill="#1e3a5c" font-weight="600">真实指标锚点</text>
  <text x="24" y="152" font-size="11" fill="#46433a">碳酸锂现货 2023-12 约 9.4 万元/吨 → 2026-08 约 15.4 万元/吨</text>
  <text x="24" y="172" font-size="11" fill="#46433a">电池产量 2026-08 约 23.7 万单位（当月）</text>
  <text x="24" y="192" font-size="11" fill="#46433a">宁德 2026Q1 市占 47.7%（定性）· 研发费用率 5.2% / 7.9%</text>
  <text x="24" y="220" font-size="11" fill="#8f8a7a">装机量结构化序列后端未返回 · ${DEMO_BANNER}</text>
</svg>`

export function cloneCharts(): ChartItem[] {
  return [
    {
      chart_id: 'CHART-LI',
      title: '工业级碳酸锂现货价（真实序列）',
      chart_type: 'line',
      template: 'trend',
      color_theme: 'navy-gold',
      unit_revision: 1,
      in_report: true,
      status: 'active',
      render_mode: 'echarts',
      option: lithiumOption(),
      compatible_templates: ['trend'],
      insight_goal: '回答问题三：价格走势（真实宏观）',
    },
    {
      chart_id: 'CHART-OUT',
      title: '动力和其他电池产量当月值（真实）',
      chart_type: 'bar',
      template: 'combo',
      color_theme: 'navy-gold',
      unit_revision: 1,
      in_report: true,
      status: 'active',
      render_mode: 'echarts',
      option: outputOption(),
      compatible_templates: ['combo', 'trend'],
      insight_goal: '回答问题一：装机景气代理指标',
    },
    {
      chart_id: 'CHART-RD',
      title: '主要企业研发费用率 2025（真实推算）',
      chart_type: 'bar',
      template: 'hbar',
      color_theme: 'navy-gold',
      unit_revision: 1,
      in_report: true,
      status: 'active',
      render_mode: 'echarts',
      option: rdOption(),
      compatible_templates: ['hbar'],
      insight_goal: '回答问题四：研发强度',
    },
    {
      chart_id: 'CHART-SHARE',
      title: '装机份额（公开口径补充）',
      chart_type: 'bar',
      template: 'hbar',
      color_theme: 'navy-gold',
      unit_revision: 1,
      in_report: true,
      status: 'active',
      render_mode: 'echarts',
      option: shareOption(),
      compatible_templates: ['hbar'],
      insight_goal: '回答问题二：份额（后端缺口，已标注）',
    },
    {
      chart_id: 'CHART-CHAIN',
      title: '动力电池产业链结构',
      chart_type: 'industry_chain',
      template: 'chain-svg',
      color_theme: 'navy-gold',
      unit_revision: 1,
      in_report: true,
      status: 'active',
      render_mode: 'svg',
      svg: CHAIN_SVG,
      compatible_templates: ['chain-svg'],
      insight_goal: '结构关系示意',
    },
  ]
}

export function cloneChapters(): ChapterItem[] {
  return REAL_CHAPTERS_RAW.map((ch) => ({
    chapter_id: ch.chapter_id,
    // 纯标题，与真实后端一致（chapter_writer/outline.py 只写标题、不写序号）。
    // 曾在此加「N、」前缀，导致前端要用正则反向剥离；编号已改由 chapter_id 反推。
    title: ch.title,
    order: ch.order,
    upstream_hint: null,
    sections: ch.sections.map((sec) => ({
      section_id: sec.section_id,
      title: sec.title,
      paragraphs: sec.paragraphs.map((p) => ({
        paragraph_id: p.paragraph_id,
        section_id: p.section_id,
        text: p.text,
        version: 1,
        status: 'active' as const,
        history: [{ version: 1, text: p.text }],
        diff: null,
      })),
    })),
  }))
}

export function cloneArtifacts(settings: ReportSettings = defaultReportSettings): ArtifactItem[] {
  const md = [
    `# ${DEMO_TITLE}`,
    '',
    `> ${DEMO_BANNER}`,
    '',
    '## 研究问题',
    ...DEMO_QUESTIONS.map((q, i) => `${i + 1}. ${q}`),
    '',
    '## 真实关键结论（摘自后端 LLM 分析）',
    ...cloneClaims()
      .slice(0, 6)
      .map((c) => `- **${c.claim_id}**：${c.statement}`),
    '',
    '## 数据缺口',
    '- 装机量权威结构化序列：SkillHub 各通道未返回',
    '- 中创新航装机份额：无结构化数据',
    '',
    '## 来源',
    `- 后端真实流水线 run：${REAL_RUN_ID}`,
    '- 问财财务 / 宏观；Agent2/4 LLM 结论与章节',
    '',
    DEMO_BANNER,
  ].join('\n')
  return [
    {
      artifact_id: 'ART-001',
      kind: 'report_markdown',
      uri: 'demo/battery-real.md',
      revision: 1,
      format_label: 'Markdown',
      generated_at_label: FIXED_NOW,
      content: md,
    },
    {
      artifact_id: 'ART-002',
      kind: 'report_html',
      uri: 'demo/battery-real.html',
      revision: 1,
      format_label: 'HTML',
      generated_at_label: FIXED_NOW,
      /*
       * 由 fusedReportHtml.ts 按真实后端模板结构生成（封面/目录/执行摘要/逐章正文/
       * 图表/来源索引），样式复用从真实产物捕获的 CSS —— 这样报告预览页看到的
       * 就是「融合完成后的成品」样子，而不是把 markdown 塞进 <pre>。
       * 仅取带 svg 的图表，无 svg 的无法内联渲染。
       */
      content: buildFusedReportHtml({
        title: DEMO_TITLE,
        topic: '动力电池行业',
        asOf: '2026-01-15',
        generatedAt: FIXED_NOW,
        depthLabel: '标准版',
        statusLabel: '附限制条件可交付',
        banner: DEMO_BANNER,
        questions: DEMO_QUESTIONS,
        chapters: cloneChapters(),
        charts: cloneCharts().filter((chart) => Boolean(chart.svg)),
        evidences: cloneEvidence(),
        claims: cloneClaims(),
      }),
    },
    {
      artifact_id: 'ART-003',
      kind: 'report_pdf',
      uri: 'demo/battery-real.pdf',
      revision: 1,
      format_label: 'PDF',
      generated_at_label: FIXED_NOW,
      content: `演示产物 PDF 占位\n${DEMO_TITLE}\n${DEMO_BANNER}\nformats=${JSON.stringify(settings.formats)}\n`,
    },
  ]
}

export function cloneRisks(): RiskItem[] {
  return [
    {
      risk_code: 'REQUESTED-DATA-UNAVAILABLE',
      title: '装机量/份额结构化数据缺口',
      description:
        '后端 SkillHub 未返回权威装机量与中创新航份额序列，报告以产量代理与公开口径补充并标注。',
      requires_ack: true,
      stage: 'data_fetch',
      acknowledged: false,
    },
    {
      risk_code: 'RISK-LI-VOLATILITY',
      title: '碳酸锂现货波动',
      description: '真实序列显示 2026 年价格先升后回，短端波动大，成本传导需滚动跟踪。',
      requires_ack: false,
      stage: 'chart_generate',
      acknowledged: false,
    },
    {
      risk_code: 'RISK-FIN-UNAUDITED',
      title: '财务数据未经审计且存在前视',
      description: '2025 财年数据为 B 级终端口径，部分晚于研究时点，仅作参考。',
      requires_ack: false,
      stage: 'data_interpret',
      acknowledged: false,
    },
  ]
}
