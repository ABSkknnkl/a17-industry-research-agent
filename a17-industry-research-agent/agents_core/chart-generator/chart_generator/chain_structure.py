"""产业链**结构类型**判别与骨架模板（2026-10-20）。

═════════════════════════════════════════════════════════════════════════════
为什么需要它（实测根因）
═════════════════════════════════════════════════════════════════════════════

主题「白酒」原先落到 ``generic``（通用硬件制造），于是合成拓扑是
「核心部件 / 关键材料 / 专用设备 / 整机制造与总装」，LLM 再把缺口翻译成
「白酒酿造设备 / 包装材料 / 酒糟回收」——**搜的全是设备厂与回收站广告**。

对照实验（同一博查、同一域名白名单）：

| query 组 | 原始 | 白名单放行 |
|---|---|---|
| 模板环节（酿造设备/包材/酒糟） | 28 | **1** |
| 真实环节（高粱小麦/酒曲发酵/经销商商超） | 30 | **13** |

→ 根因不是检索、不是白名单、不是 query 措辞，是**结构选错**。
本模块把"查不到就掉 generic"改成"先判结构、再选骨架"。

═════════════════════════════════════════════════════════════════════════════
判别树（顺序即优先级）
═════════════════════════════════════════════════════════════════════════════

1. 离散硬件制造：有"把零部件装成整机"的环节
2. 消费品制造：原料/配方 → 连续加工 → 品牌 → 多层渠道 → 个人消费
3. 流程工业：资源在装置里连续反应/冶炼，没有"组装"
4. 医药/医疗：研发审批驱动，强监管、长周期
5. 数字/技术分层：没有实体产品，全是软件/算力/内容
6. 服务/网络平台：撮合供需，不生产实物

农业按用户裁定并入 **模板 2 变体**（原料层前加"种业/养殖"）。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StageTemplate:
    """一个环节骨架（只描述"该有什么环节"，不含具体公司）。"""

    stage: str                       # upstream | midstream | downstream | support
    label: str                       # 环节名（绘制用，≤8 字优先）
    key_products: tuple[str, ...] = ()
    is_core: bool = False            # 整机/品牌/主体节点
    flow_out: str = "material"       # material | technical | service | recycle


@dataclass(frozen=True)
class StructureSpec:
    """一种产业链结构。"""

    key: str
    name: str
    question: str                    # 判别问句（写进提示词，帮 LLM 自检）
    signal_words: tuple[str, ...]    # 判别关键词
    stages: tuple[StageTemplate, ...]
    # 缺口类型 → 该结构下的行业标准检索词（覆盖 _GAP_QUERY_TERMS 的通用模板）
    query_terms: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # 传递给 A2/A3 提示词的结构说明（替换"硬件四段式"那段）
    prompt_block: str = ""


# ── 1. 离散硬件制造（现有模板）──────────────────────────────────────────────
_DISCRETE = StructureSpec(
    key="discrete",
    name="离散硬件制造",
    question="有没有「把一堆零部件装成一台整机」的环节？",
    signal_words=(
        "机器人", "无人机", "汽车", "整车", "设备", "手机",
        "激光雷达", "面板", "机床", "服务器", "连接器", "零部件",
        "整机", "装备", "风电", "储能系统", "船舶", "航空",
        "卫星", "雷达", "传感器", "空调", "冰箱", "洗衣机",
        "家电", "机械", "器件", "模组", "电机", "机械臂",
        "工程机械",
    ),
    stages=(
        StageTemplate("upstream", "核心部件", ("核心零部件",)),
        StageTemplate("upstream", "关键材料", ("原材料",)),
        StageTemplate("upstream", "基础器件", ("元器件",)),
        StageTemplate("upstream", "专用设备", ("生产设备",)),
        StageTemplate("upstream", "检测仪器", ("检测设备",)),
        StageTemplate("midstream", "研发与设计", ("设计方案",), flow_out="technical"),
        StageTemplate("midstream", "整机制造与总装", ("整机",), is_core=True),
        StageTemplate("downstream", "工业应用", ("工业场景",)),
        StageTemplate("downstream", "消费应用", ("消费场景",)),
        StageTemplate("downstream", "政府采购", ("公共项目",)),
        StageTemplate("downstream", "海外市场", ("出口",)),
        StageTemplate("support", "测试与认证", ("认证服务",), flow_out="service"),
        StageTemplate("support", "运维与回收", ("运维",), flow_out="service"),
        StageTemplate("support", "软件与数据服务", ("软件",), flow_out="service"),
    ),
    query_terms={
        "missing_core_body": ("整机厂商 代表企业", "龙头企业 上市公司"),
        "sparse_upstream": ("核心零部件 供应商", "上游 材料 器件 供应商"),
        "no_company_nodes": ("代表企业 供应商 上市公司"),
        "thin_brand_list": ("整机厂商 龙头企业", "整机厂 品牌"),
        "missing_recycle": ("运维 回收 再制造", "售后 维修 服务商"),
        "missing_support_layer": ("基础设施 运行保障"),
        "uncovered_topic": ("{parts} 供应商 厂商", "{subject} 品牌 厂商 龙头企业"),
    },
    prompt_block="""
【结构类型：离散硬件制造】
四段式：上游各类外购零部件与材料（并行供给）→ 中游研发与整机制造 → 整机/本体（品牌卡）→ 下游场景，下方配套带。
中游必须有一个 is_core=true 的整机/本体节点，其 companies 即品牌列表（2-8 家真实整机厂）。
上游零部件是"并行供给"关系，不是先后工序，禁止逐节点连线。
🔴 上游五张卡的标题要写成**具体品类**（如结构件与机壳/显示面板/存储芯片/电池模组），
不要用「核心零部件」「关键材料」这类没有信息量的词当标题——那是角色，不是环节。
""",
)


_CONSUMER = StructureSpec(
    key="consumer",
    name="消费品制造",
    question="产品是不是通过品牌 + 渠道卖给个人消费者的快消品？",
    signal_words=(
        "白酒", "啤酒", "黄酒", "乳制品", "调味品", "饮料",
        "食品", "零食", "化妆品", "美妆", "护肤", "烟草",
        "茶饮", "咖啡", "预制菜", "粮油", "日化", "个护",
        "宠物食品", "保健品", "食品加工", "烘焙", "罐头", "保健食品",
    ),
    stages=(
        StageTemplate("upstream", "农产品原料", ("高粱", "小麦", "大米", "糯米", "玉米", "水果", "原奶",)),
        StageTemplate("upstream", "辅料与酒曲", ("酒曲", "酒母", "酵母", "香精", "添加剂",)),
        StageTemplate("upstream", "包装材料", ("玻璃瓶", "纸盒", "瓶盖", "标签", "外箱",)),
        StageTemplate("upstream", "生产设备", ("发酵窖池", "蒸馏设备", "灌装线",)),
        StageTemplate("midstream", "制曲与糖化发酵", ("制曲", "糖化", "发酵",)),
        StageTemplate("midstream", "蒸馏与陈酿老熟", ("蒸馏取酒", "陶坛储存", "陈酿老熟",)),
        StageTemplate("midstream", "勾调与灌装", ("酒体勾调", "灌装成品",)),
        StageTemplate("midstream", "品牌与产品运营", ("品牌产品",), is_core=True),
        StageTemplate("downstream", "经销商与批发代理", ("总代", "区域代理",)),
        StageTemplate("downstream", "烟酒专卖店与终端", ("品牌专卖店", "烟酒店", "商超卖场",)),
        StageTemplate("downstream", "团购与特通渠道", ("政企团购", "商务宴席", "餐饮",)),
        StageTemplate("downstream", "电商与即时零售", ("电商", "直播", "即时零售",)),
        StageTemplate("support", "仓储与物流", ("仓储", "物流配送",), flow_out="service"),
        StageTemplate("support", "品牌营销与数字直销", ("营销", "自营 App", "专卖店",), flow_out="service"),
        StageTemplate("support", "副产品综合利用", ("酒糟", "果渣", "饲料化",), flow_out="recycle"),
        StageTemplate("support", "食品安全与认证", ("质检", "食安认证", "质量追溯",), flow_out="service"),
    ),
    query_terms={
        "missing_core_body": ("龙头品牌 市场份额", "知名品牌 企业"),
        "sparse_upstream": ("原料 供应商", "包装材料 供应商", "酒曲 供应商"),
        "no_company_nodes": ("品牌 企业", "生产商 厂家"),
        "thin_brand_list": ("龙头品牌 企业排名", "知名品牌"),
        "missing_recycle": ("副产品 综合利用", "酒糟 果渣 处理"),
        "missing_support_layer": ("仓储 物流", "经销商 渠道", "即时零售"),
        "uncovered_topic": ("{parts} 企业", "{subject} 龙头企业 品牌"),
    },
    prompt_block="""
【结构类型：消费品制造】
链条：农产品原料 → 辅料/酒曲/包装 → 制曲发酵 → 蒸馏陈酿 → 勾调灌装 → 品牌商（核心）→ 四类渠道，配套仓储/营销/副产品/食安。
🔴 本结构没有"整机"概念：
- is_core 只能标在「品牌与产品运营」，companies 是品牌商（白酒：茅台/五粮液/泸州老窖/汾酒/洋河/古井贡酒），不是设备厂；
- 禁止「核心部件/整机制造/总装」；
- 上游必须从农产品原料开始，且不放"检测品控"（内部质检并入配套"食品安全与认证"，不是采购物料）；
- 下游只列"渠道"（经销/专卖/团购/电商），不写"个人消费者"——消费者是渠道服务对象，不是产业链环节；
- 生产必须按真实工序逐道呈现：制曲发酵 → 蒸馏取酒 → 陈酿老熟 → 勾调 → 灌装，陈酿和勾调不得遗漏；
- 非酒类消费品（食品/饮料/乳制品/化妆品）：将"制曲/蒸馏/陈酿/勾调"替换为对应工序（调配、杀菌、乳化、发酵等），骨架不变。
""",
)


_PROCESS = StructureSpec(
    key="process",
    name="流程工业 / 纵向工序链",
    question="是不是在装置中连续生产、或经多道工序首尾相接（无零件并行组装）？",
    signal_words=(
        "石化", "化工", "钢铁", "电解铝", "水泥", "造纸",
        "化纤", "冶炼", "炼化", "化肥", "农药", "玻璃",
        "陶瓷", "有色金属", "煤炭", "焦化", "纯碱", "氯碱",
        "树脂", "橡胶", "涂料", "油墨", "工业气体", "光伏",
        "多晶硅", "工业硅", "硅料", "硅片", "电池片", "组件",
        "锂电", "锂电池", "正极", "负极", "电解液", "隔膜",
        "电芯", "电池材料", "半导体", "晶圆", "封测", "面板",
        "显示面板", "OLED", "LCD", "阵列", "成盒", "模组",
    ),
    stages=(
        StageTemplate("upstream", "矿产/基础原料", ("矿石", "原油", "煤炭", "石英", "工业硅", "锂钴镍",)),
        StageTemplate("upstream", "能源与公用工程", ("电力", "蒸汽", "天然气",)),
        StageTemplate("upstream", "辅料/催化剂", ("催化剂", "溶剂", "添加剂",)),
        StageTemplate("upstream", "装置与设备", ("反应釜", "窑炉", "产线设备",)),
        StageTemplate("midstream", "工序①·初加工提纯", ("冶炼", "裂解", "提纯", "合成", "阵列",)),
        StageTemplate("midstream", "工序②·精加工反应", ("精制", "反应", "成盒", "电芯制造",)),
        StageTemplate("midstream", "工序③·成型成品", ("型材", "成品", "组件", "封测", "模组",), is_core=True),
        StageTemplate("downstream", "制造业客户", ("工业客户", "整车厂", "整机厂",)),
        StageTemplate("downstream", "基建/农业客户", ("建材", "电站", "化肥",)),
        StageTemplate("downstream", "消费/出口", ("终端", "出口",)),
        StageTemplate("support", "环保与三废处理", ("环保", "循环",), flow_out="service"),
        StageTemplate("support", "物流与仓储", ("物流", "储罐",), flow_out="service"),
        StageTemplate("support", "检测与标准", ("检测", "认证",), flow_out="service"),
        StageTemplate("support", "副产物综合利用", ("矿渣", "余料",), flow_out="recycle"),
        StageTemplate("support", "工艺软件与仿真", ("DCS", "流程仿真",), flow_out="service"),
    ),
    query_terms={
        "missing_core_body": ("龙头 产能 企业", "成品环节 主要生产企业"),
        "sparse_upstream": ("原料 供应", "矿产 能源 供应"),
        "no_company_nodes": ("生产企业", "厂家"),
        "thin_brand_list": ("龙头 企业 产能排名"),
        "missing_recycle": ("三废 处理 循环利用", "副产物"),
        "missing_support_layer": ("环保 物流 配套"),
        "uncovered_topic": ("{parts} 生产企业", "{subject} 龙头企业"),
    },
    prompt_block="""
【结构类型：流程工业/纵向工序链】
链条：矿产/原料 → 能源/辅料/装置 → 工序①②③（核心）→ 下游客户，配套环保/物流/检测。
🔴 槽位命名例外：中游「工序①/②/③」是**占位名**，必须按行业真实工序改名，
   禁止照抄"初加工/精加工/成型"；上游 4 个槽位保持固定名。
- 光伏：工序①工业硅/多晶硅提纯 → 工序②硅片/电池片 → 工序③组件（隆基/晶科/天合）
- 锂电：工序①四大主材（正极/负极/电解液/隔膜）→ 工序②电芯 → 工序③Pack（宁德/比亚迪/亿纬）
- 半导体：工序①设计 → 工序②晶圆制造 → 工序③封测（中芯/华虹/长电/通富）
- 面板：工序①阵列 → 工序②成盒 → 工序③模组（京东方/TCL华星/维信诺）
- 石化：工序①炼油 → 工序②化工 → 工序③成品；钢铁：炼铁 → 炼钢 → 轧钢
工序是"先后承接"，列内按工序顺序纵向排列，列间用粗箭头，不逐节点连线。
""",
)


_PHARMA = StructureSpec(
    key="pharma",
    name="医药/医疗",
    question="是不是要经过临床/注册审批才能上市？",
    signal_words=(
        "医", "药", "疫苗", "器械", "CXO", "CDMO",
        "CRO", "临床", "生物", "诊断", "IVD", "中药",
        "细胞", "基因", "抗体", "ADC", "处方药", "医院",
    ),
    stages=(
        StageTemplate("upstream", "原料药与中间体", ("API", "中间体",)),
        StageTemplate("upstream", "试剂与耗材", ("试剂", "培养基",)),
        StageTemplate("upstream", "研发与生产设备", ("反应罐", "纯化设备",)),
        StageTemplate("midstream", "药物发现与临床前", ("候选分子",), flow_out="technical"),
        StageTemplate("midstream", "临床试验（Ⅰ/Ⅱ/Ⅲ期）", ("临床数据",), flow_out="technical"),
        StageTemplate("midstream", "商业化生产", ("上市产品",), is_core=True),
        StageTemplate("downstream", "医院与临床", ("处方",)),
        StageTemplate("downstream", "药店与零售", ("零售", "DTP",)),
        StageTemplate("downstream", "医保与支付", ("支付",), flow_out="service"),
        StageTemplate("support", "注册与监管（NMPA）", ("审评审批",), flow_out="service"),
        StageTemplate("support", "CRO/CDMO 服务", ("外包服务",), flow_out="service"),
        StageTemplate("support", "冷链与药物警戒", ("冷链", "召回",), flow_out="service"),
    ),
    query_terms={
        "missing_core_body": ("龙头 药企 上市产品", "主要企业"),
        "sparse_upstream": ("原料药 供应商", "试剂 耗材 供应商"),
        "no_company_nodes": ("企业", "生产企业"),
        "thin_brand_list": ("龙头 药企 排名"),
        "missing_recycle": ("药物警戒 召回"),
        "missing_support_layer": ("冷链 物流 CRO"),
        "uncovered_topic": ("{parts} 企业", "{subject} 龙头企业"),
    },
    prompt_block="""
【结构类型：医药/医疗】
链条：原料药/试剂 → 药物发现 → 临床（Ⅰ/Ⅱ/Ⅲ期）→ 商业化生产（核心）→ 医院/药店 → 医保支付，配套 CRO/CDMO/冷链/监管。
🔴 监管职能（注册/NMPA/审批）单列在配套层，不得并入中游环节名（F16 教训）；
is_core 标在持证生产企业（恒瑞/百济/信达等）；禁止"整机/系统集成/适航"等硬件词。
""",
)


_DIGITAL = StructureSpec(
    key="digital",
    name="数字/技术分层",
    question="有没有「装出来的东西」？没有，全是软件/算力/模型/内容。",
    signal_words=(
        "软件", "SaaS", "大模型", "AI", "游戏", "互联网",
        "数据", "云计算", "算法", "内容", "平台", "APP",
        "应用", "系统", "数字化", "信创", "操作系统", "数据库",
        "中间件", "安全", "区块链", "元宇宙", "IT", "云服务",
        "智能体", "AIGC",
    ),
    stages=(
        StageTemplate("upstream", "算力基础设施", ("AI 芯片", "服务器", "数据中心", "液冷",)),
        StageTemplate("upstream", "数据与语料", ("采集", "清洗", "标注", "数据交易",), flow_out="service"),
        StageTemplate("upstream", "基础软件与框架", ("操作系统", "框架", "工具链",), flow_out="technical"),
        StageTemplate("midstream", "基础模型/大模型", ("通用大模型", "行业模型",), is_core=True, flow_out="technical"),
        StageTemplate("midstream", "技术能力", ("计算机视觉", "NLP", "语音", "智能体",), flow_out="technical"),
        StageTemplate("midstream", "平台与中间件", ("开发平台", "MLOps", "低代码",), flow_out="technical"),
        StageTemplate("downstream", "应用与产品", ("行业应用", "软件产品",), flow_out="service"),
        StageTemplate("downstream", "企业客户", ("企业采购",), flow_out="service"),
        StageTemplate("downstream", "个人用户", ("订阅", "付费",), flow_out="service"),
        StageTemplate("downstream", "生态与渠道", ("ISV", "集成商",), flow_out="service"),
        StageTemplate("support", "运维与安全", ("云安全", "运维",), flow_out="service"),
        StageTemplate("support", "开发者生态", ("开源社区", "开发者",), flow_out="service"),
    ),
    query_terms={
        "missing_core_body": ("头部厂商 市场份额", "大模型 代表企业"),
        "sparse_upstream": ("算力 数据 供应商"),
        "no_company_nodes": ("厂商", "企业"),
        "thin_brand_list": ("头部厂商 排名"),
        "missing_recycle": ("运维 服务商"),
        "missing_support_layer": ("云服务 安全"),
        "uncovered_topic": ("{parts} 厂商", "{subject} 头部企业"),
    },
    prompt_block="""
【结构类型：数字/技术分层】
四层：基础层（算力/数据/基础软件）→ 模型层（大模型/技术能力）→ 平台层（中间件/开发平台）→ 应用层（产品/客户），配套运维安全与开发者生态。
🔴 无物料流：连线一律用 technical/service，禁止 material；
禁止「零部件/整机/总装/产能」；is_core 标在"基础模型/大模型"（或纯应用类产品的"应用产品"）。
""",
)


_SERVICE = StructureSpec(
    key="service",
    name="服务/网络平台",
    question="是不是撮合供需、或提供履约/持牌服务，本身不生产实物？",
    signal_words=(
        "物流", "快递", "银行", "保险", "证券", "外卖",
        "电商", "文旅", "旅游", "养老", "教育", "零售",
        "酒店", "餐饮服务", "出行", "货运", "供应链", "租赁",
        "维修服务", "咨询", "中介", "平台经济", "免税", "基金",
        "信托", "支付", "人力资源", "物业",
    ),
    stages=(
        StageTemplate("upstream", "供给端主体", ("商品/服务/内容/资金供给方",), flow_out="service"),
        StageTemplate("upstream", "基础设施与技术", ("场地", "IT", "设备", "网点",), flow_out="service"),
        StageTemplate("midstream", "平台/服务主体", ("撮合平台 或 履约/持牌机构",), is_core=True, flow_out="service"),
        StageTemplate("midstream", "履约与调度", ("交付", "运营", "调度",), flow_out="service"),
        StageTemplate("downstream", "个人用户（C 端）", ("消费者", "储户", "旅客",), flow_out="service"),
        StageTemplate("downstream", "企业客户（B 端）", ("企业", "商户",), flow_out="service"),
        StageTemplate("downstream", "政府与公共（G 端）", ("政府", "公共服务",), flow_out="service"),
        StageTemplate("support", "支付与结算", ("支付", "清算",), flow_out="service"),
        StageTemplate("support", "风控与合规", ("风控", "监管", "牌照",), flow_out="service"),
        StageTemplate("support", "客服与运营", ("客服", "售后",), flow_out="service"),
        StageTemplate("support", "信息与数据服务", ("信息平台", "SaaS",), flow_out="service"),
    ),
    query_terms={
        "missing_core_body": ("头部平台/机构 市场份额", "代表企业"),
        "sparse_upstream": ("供给端 服务商", "基础设施"),
        "no_company_nodes": ("服务商", "平台企业", "机构"),
        "thin_brand_list": ("头部平台/机构 排名"),
        "missing_recycle": ("售后 服务"),
        "missing_support_layer": ("支付 风控 系统"),
        "uncovered_topic": ("{parts} 服务商", "{subject} 头部企业"),
    },
    prompt_block="""
【结构类型：服务/网络平台】
网络结构：供给端 → 平台/服务主体（核心）→ 履约调度 → 用户端（C/B/G），配套支付/风控合规/客服。
🔴 无物料流；禁止「零部件/整机/产能」。
- 撮合平台（外卖/网约车/电商）：is_core 标在"平台"，companies 是平台企业；
- 履约/持牌服务商（银行/物流/保险/医院/教培）：is_core 标在"服务主体"，
  companies 是机构（如银行、券商、物流商），不得误标为"平台"。
""",
)


STRUCTURES: tuple[StructureSpec, ...] = (
    _DISCRETE, _CONSUMER, _PROCESS, _PHARMA, _DIGITAL, _SERVICE,
)

STRUCTURE_MAP: dict[str, StructureSpec] = {s.key: s for s in STRUCTURES}

# 结构专属的列头文案（2026-10-22）：`STAGE_TITLES_FULL` 是硬件四段式的通用文案，
# 白酒用它会出现"中游：设计研发与制造集成"这种明显不对的列头（实测 run-20261022111644）。
STRUCTURE_STAGE_TITLES: dict[str, dict[str, str]] = {
    "discrete": {"upstream": "上游：核心供给与零部件",
                 "midstream": "中游：本体制造与系统集成",
                 "downstream": "下游：场景与终端应用"},
    "consumer": {"upstream": "上游：原料与包装供给",
                 "midstream": "中游：生产与品牌运营",
                 "downstream": "下游：渠道与终端消费"},
    "process": {"upstream": "上游：资源与能源供给",
                "midstream": "中游：冶炼加工与精制",
                "downstream": "下游：工业与消费客户"},
    "pharma": {"upstream": "上游：原料与研发生产设备",
               "midstream": "中游：研发、临床与商业化",
               "downstream": "下游：医疗终端与支付"},
    "digital": {"upstream": "上游：算力、数据与模型",
                "midstream": "中游：平台与应用产品",
                "downstream": "下游：企业与个人用户"},
    "service": {"upstream": "上游：供给端与基础设施",
                "midstream": "中游：平台撮合与履约",
                "downstream": "下游：C/B/G 三端用户"},
}


def stage_titles(subject: str = "") -> dict[str, str]:
    """该主题应使用的列头文案。画像有专属 ``mid_column`` 时优先用它覆盖中游。"""
    from chart_generator.chain_graph import STAGE_TITLES_FULL  # noqa: PLC0415

    titles = dict(STAGE_TITLES_FULL)
    try:
        key = detect_structure(subject).key
    except Exception:                                          # pragma: no cover
        key = "discrete"
    titles.update(STRUCTURE_STAGE_TITLES.get(key, {}))
    try:
        from chart_generator.chain_profile import detect_profile  # noqa: PLC0415

        prof = detect_profile(subject)
        mid_col = str(prof.get("mid_column") or "").strip()
        if mid_col and prof.get("key") != "generic":
            titles["midstream"] = f"中游：{mid_col}"
    except Exception:                                          # pragma: no cover
        pass
    return titles


# 复合词消歧（2026-10-22 V2）：靠"末尾词"覆盖按词数计的判定，避免
# 「医药电商」被判 pharma、「光伏设备」被判 process、「汽车金融」被判 discrete。
_COMPOUND_SUFFIX_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("金融", "电商", "服务", "平台", "支付", "出行", "物流"), "service"),
    (("设备", "装备"), "discrete"),
    (("材料", "化工", "纤维", "树脂", "胶膜"), "process"),
    (("电子", "智能硬件"), "discrete"),
)


def _disambiguate_compound(subject: str) -> str:
    """按末尾词消歧，返回结构 key；未命中返回空串。"""
    s = str(subject or "").strip()
    for suffixes, key in _COMPOUND_SUFFIX_RULES:
        if s and s.endswith(suffixes):
            return key
    return ""


def detect_structure(subject: str) -> StructureSpec:
    """判别行业结构类型（顺序即优先级，命中数多者胜）。

    默认返回 ``discrete``——大多数产业链研究主题是硬件制造；
    但它只是**兜底**，不是"查不到就 generic"。
    """
    text = str(subject or "")
    if not text:
        return _DISCRETE
    # Reviewed full-chain structure outranks the heuristic discriminators.
    # A3's LAYOUT_GUIDE only describes layout; the segment skeleton comes
    # from StructureSpec.stages, so this is the single place to make A2/A3
    # share the same three-segment view.  Industries without a reviewed card
    # keep the original decision tree untouched (F1-F17 regression guards).
    try:
        from chart_generator.chain_facts import try_load_chain_facts

        facts = try_load_chain_facts(text)
    except Exception:                                        # pragma: no cover
        facts = None
    if facts is not None:
        stages = tuple(
            StageTemplate(
                stage=seg.stage,
                label=seg.name.split("：", 1)[-1][:8],
                key_products=tuple(seg.key_products),
                is_core=(seg.stage == "midstream"),
                flow_out="material",
            )
            for seg in facts.segments
            if seg.stage in ("upstream", "midstream", "downstream")
        )
        return StructureSpec(
            key=f"reviewed_{facts.profile_key}",
            name=f"{facts.profile_key} 已审定全链三段",
            question="本主题已有人工审定的全链三段结构，不得另立骨架。",
            signal_words=(),
            stages=stages,
            prompt_block=(
                "【已审定全链三段骨架（固定槽位，不得增删、改名、并段）】\n"
                + "\n".join(f"- {s.stage}: {s.label}" for s in stages)
                + "\n证据不足的槽位只留空 companies，description 仍说明该环节做什么。"
            ),
        )
    # 复合词消歧优先：先看末尾词（医药电商→service、光伏设备→discrete、半导体材料→process）
    _cmp_key = _disambiguate_compound(text)
    if _cmp_key in STRUCTURE_MAP:
        return STRUCTURE_MAP[_cmp_key]
    best: tuple[int, int, StructureSpec] | None = None
    for idx, spec in enumerate(STRUCTURES):
        hits = sum(1 for w in spec.signal_words if w in text)
        if not hits:
            continue
        candidate = (hits, -idx, spec)          # 命中数优先，其次表格顺序
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    return best[2] if best else _DISCRETE


# 槽位数量安全上限（与渲染容量对齐：上游 8 / 中游 5 / 下游 8 / 配套 6）
_SLOT_CAP = {"upstream": 8, "midstream": 5, "downstream": 8, "support": 6}

_CORE_NAME_HINTS = ("本体", "整机", "总装", "组装", "生产", "制造", "品牌", "集成")

# 研发/算法类环节的流向（只出图纸与授权，不接实物）
_RD_HINTS = ("研发", "设计", "算法", "软件", "仿真", "工艺研发", "配方")


@dataclass(frozen=True)
class Slot:
    """一个「必须存在」的环节槽位。"""

    stage: str
    label: str
    is_core: bool = False
    flow_out: str = "material"


def _split_names(text: Any, cap: int) -> list[str]:
    """把画像里的「A、B、C」串拆成环节名列表。"""
    if isinstance(text, (list, tuple)):
        raw = [str(x) for x in text]
    else:
        raw = [x for x in str(text or "").replace("，", "、").split("、")]
    out: list[str] = []
    for item in raw:
        name = str(item).strip().strip("。；;")
        if name and name not in out:
            out.append(name)
    return out[:cap]


def _slots_from_stages(spec: StructureSpec) -> list[Slot]:
    return [Slot(s.stage, s.label, s.is_core, s.flow_out) for s in spec.stages]


def _slots_from_profile(prof: dict) -> list[Slot]:
    """有专属画像 → 用画像的四个清单当槽位（比结构骨架更细、更贴合行业）。"""
    slots: list[Slot] = []
    for name in _split_names(prof.get("upstream") or [], _SLOT_CAP["upstream"]):
        slots.append(Slot("upstream", name, False, "material"))

    mids = prof.get("mid_cards") or []
    mid_names: list[tuple[str, str]] = []
    for card in mids:
        if isinstance(card, (list, tuple)):
            mid_names.append((str(card[0]), str(card[1]) if len(card) > 1 else ""))
        else:
            mid_names.append((str(card), ""))
    core_idx = next((i for i, (n, _d) in enumerate(mid_names)
                     if any(h in n for h in _CORE_NAME_HINTS)), 0 if mid_names else -1)
    for i, (name, _desc) in enumerate(mid_names[:_SLOT_CAP["midstream"]]):
        flow = "technical" if any(h in name for h in _RD_HINTS) else "material"
        slots.append(Slot("midstream", name, i == core_idx, flow))

    for name in _split_names(prof.get("downstream") or "", _SLOT_CAP["downstream"]):
        slots.append(Slot("downstream", name, False, "material"))
    for name in _split_names(prof.get("support") or "", _SLOT_CAP["support"]):
        slots.append(Slot("support", name, False, "service"))
    return slots


def resolve_slots(subject: str = "") -> tuple[list[Slot], str]:
    """决定这张图用哪套槽位。返回 ``(槽位列表, 来源说明)``。

    🔴 优先级（必须写死，否则模型会二选一随机）：
      ① 有专属画像（``profile.upstream`` 非空）→ 用**画像**（细，如 quadruped 7 项上游）
      ② 落到 generic（无画像）→ 用**结构骨架**（兜底，如 consumer 16 项）
    结构在这一层退化为"stage 归属校验 + 数量上限"，不再决定环节名。
    """
    spec = detect_structure(subject)
    try:
        from chart_generator.chain_profile import detect_profile   # noqa: PLC0415

        prof = detect_profile(subject)
    except Exception:                                              # pragma: no cover
        prof = {}
    if prof.get("upstream"):
        slots = _slots_from_profile(prof)
        if slots:
            return slots, f"画像（{prof.get('scope_key') or prof.get('key')}）"
    return _slots_from_stages(spec), f"结构骨架（{spec.key}）"


def structure_prompt_block(subject: str = "") -> str:
    """给 A2/A3 提示词用的**结构 + 固定槽位**段落（2026-10-22 接入）。

    为什么要有这一段：实测（`output/白酒产业链_归因实验_..._20261022.md`）证明
    —— 不给骨架时模型自己出 4 大类（含酒曲/基酒/陈化）；一旦"只准用检索素材"，
    就掉到 1-2 类，"陈酿/勾调"这类**没有上市公司载体**的环节系统性消失。
    骨架必须由这里钉住，检索只负责填内容。

    🔴 2026-10-25（方案 P1「禁 generic 槽位」）：骨架钉的是**阶段、数量、核心标记**，
    **不钉环节名**。原实现把「核心部件/关键材料/基础器件/专用设备/检测仪器」当成
    合法环节名写进"不得改名"，模型只能照抄——笔记本实测 5 张上游卡的标题全是这些泛词，
    而卡里的 key_products 反而是正确品类（结构件/软包电池/玻璃盖板/存储芯片）。
    现在这类名字标 † 并明确要求改写为具体品类；修复层 `chain_ontology.relabel_generic_nodes`
    再用 items 兜底纠正（模型没照做时）。

    返回三段：结构判别说明 + 固定槽位表 + 填写规则。
    """
    spec = detect_structure(subject)
    slots, source = resolve_slots(subject)
    try:
        from chart_generator.chain_ontology import is_generic_label   # noqa: PLC0415
    except Exception:                                                 # pragma: no cover
        def is_generic_label(_x: str) -> bool:
            return False
    generic = [s.label for s in slots if is_generic_label(s.label)]
    rows = "\n".join(
        f"| {i} | {s.stage} | {s.label}{' †' if is_generic_label(s.label) else ''} | "
        f"{'★' if s.is_core else ''} | {s.flow_out} |"
        for i, s in enumerate(slots, start=1)
    )
    n_core = sum(1 for s in slots if s.is_core)
    _generic_rule = (
        f"1a. 带 † 的 {len(generic)} 个环节名是**角色占位符，不是最终环节名**：\n"
        f"    - 必须改写成该产业真实存在的**具体品类/工序**，用 2-8 个字，"
        f"能让人一眼看出这一环在做什么；\n"
        f"    - 反例（禁止照抄）：核心部件 / 关键材料 / 基础器件 / 专用设备 / 检测仪器 / "
        f"零部件 / 配件 / 其他；\n"
        f"    - 正例：笔记本电脑上游 = 结构件与机壳 / 显示面板 / 存储芯片 / 电源管理芯片 / "
        f"电池模组与电芯 / 键盘与触控模组；白酒上游 = 高粱与小麦 / 酒曲与酒母 / 玻璃瓶与瓶盖；\n"
        f"    - 该环节的 key_products 就填这些具体品类词（每个环节 2-5 个），"
        f"标题与品类必须对得上；\n"
        if generic else ""
    )
    return (
        f"【本主题结构类型：{spec.name}】判别问句：{spec.question}\n"
        f"{spec.prompt_block}\n\n"
        f"🔴【本轮固定槽位 · 共 {len(slots)} 个 · 来源：{source}】\n"
        f"| # | stage | 环节名 | 核心 | 流向 |\n|---|---|---|---|---|\n{rows}\n\n"
        f"填写规则：\n"
        f"1. 上表 stage / 槽位数量 / 核心标记是**固定槽位**：不得增删、不得并段；\n"
        f"{_generic_rule}"
        f"2. 你的任务是逐个槽位填 companies / key_products / description / phase / buyer，"
        f"**不是重新设计环节**；\n"
        f"3. 某槽位证据不足 → companies 留空、description 留空字符串，"
        f"**不要删槽位，也不要另起一个近似环节**（渲染层会表达缺失）；\n"
        f"4. 确需补充槽位以外的环节，最多加 2 个，且 description 末尾标「[补充]」；\n"
        f"5. ★ 核心槽位必须有且仅有 {n_core or 1} 个（is_core=true），其余一律 false。"
    )


def stage_templates(subject: str) -> tuple[StageTemplate, ...]:
    """该主题应使用的环节骨架（结构层原始定义，不含画像覆盖）。"""
    return detect_structure(subject).stages
