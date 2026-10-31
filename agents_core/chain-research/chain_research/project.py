"""Project transport construction at the adapter boundary."""
import json
import asyncio
import httpx
from .models import ChainResearchRequest, ChainScope, ResearchBudget, stable_id
from .providers import DoubaoSearchProvider, DocumentFetchProvider
from .service import ChainResearchService
from .store import ChainStore

PROMPTS = {
 'gap_queries': '从已有检索线索中的具体公司名提出4条官网/官方产品目录/年报查询，输出JSON:{"queries":[]}。每条围绕一个明确厂商或产品。优先补齐上游部件、中游制造或品牌的原始资料，不继续查询综合产业新闻。不要凭常识补公司。可用site限定明确的官网域名，但不要伪造域名。',
 'discover': '你是产业研究结构分析员。根据资料提出范围一致的具体活动环节，工艺不需要有上市公司。禁止泛词占位，禁止公司名单决定结构。仅输出JSON:{"activities":[{"name":"具体活动","stage":"upstream|midstream|downstream|support"}],"queries":["用于补查企业参与的短查询"]}。不超过16个活动、4个查询。查询优先覆盖各主要阶段的代表企业和原厂产品资料，保留主题、规范品类和厂家角色词，不能全用在某个小部件或边缘工艺。不提前把型号或集团供应商推断成具体客户关系。摘要只是线索，资料不足如实说明。',
 'extract': '从给定原文提取原子关系，不补常识。仅输出JSON:{"claims":[{"subject":"原文主体","subject_type":"organization|product|activity|customer_type","predicate":"requires_input|produces|precedes|offers|performs|participates_in|sells_through|supplies_to|provides_service_to","object":"客体","object_type":"实体类型","role":"相对角色","applicable_products":[],"valid_period":null,"quote":"原文连续逐字摘录"}]}。activity必须使用输入活动名。优先提取公司参与具体活动和输入输出关系，每文最多16条。提供某产品不代表向某客户实际供货。原文不支持则不提取。',
 'verify': '独立核验逐条断言与原文上下文，禁止使用生成器解释、常识、知名度来支持。检查主体、关系方向、活动归属、产品与时间范围；集团名单不证明具体机型。输出JSON:{"checks":[{"id":"输入id","supported":true,"reason":"原文如何支持或不支持该关系"}]}。仅提到名字不支持参与，无法确认返回false。',
}

async def research_project(run_id, subject, as_of, run_dir, *, emit=None, reverify_path=None, resume_cache=False,
                           research_strategy='profile_guided', profile_id=None):
    from chart_generator.config import Settings
    from chart_generator.doubao_mcp import DoubaoMcpClient, quota_status
    settings = Settings.from_env()
    transport = DoubaoMcpClient.get()
    if transport is None:
        raise RuntimeError('Project Doubao transport unavailable')
    search = DoubaoSearchProvider(transport, monthly_guard=lambda: not quota_status()['exhausted'])
    async def llm(task, payload):
        if not settings.llm_api_key:
            raise RuntimeError('Project LLM key unavailable')
        extra_rules = ('每个 organization 必须是可识别的单一具体组织。行业、企业类型、'
            '“笔记本生产企业”等类别不是组织；企业列表必须拆成独立实体。'
            '区分参与某类产品供给与亲自执行所有设计/制造工序，参与角色不得扩大。')
        if task == 'extract':
            extra_rules += ('优先提取明确的offers产品或服务关系，保留规范产品名。role如有输入allowed_roles，'
                '只在原文支持时选择其中角色，否则留空。轻薄设计、硬核电竞是属性或营销描述，不是产品。'
                '不能把整机配置中的CPU、SSD归为整机品牌独立提供的部件。'
                '不要输出is_a分类映射；类别归属由版本化政策另外判定。')
        if task == 'discover':
            extra_rules += '不要把分别由不同组织承担的设计、制造、品牌运营合成一个要求各参与者全部具备的环节。'
        if task == 'verify':
            extra_rules += ('每项还必须输出primary_source布尔值：页面必须是相关主体官网、官方原始披露或明确的原始技术资料；'
                '新闻、论坛、财富号、自媒体和转载不属于primary_source，不能因为文章引用公司就当主体披露。'
                '采购订单下达方向与供货方向相反；品牌把订单转到工厂意味着工厂向品牌供货。'
                '未来计划、据称和预计不证明当前已发生。')
            extra_rules += ('每项还必须输出in_scope布尔值。断言必须属于本研究主题，'
                '官网导航里的手机、服务器、路由器等其他产品不因与笔记本同属一品牌就进入笔记本产业链。'
                '型号配置中的SSD/显示屏/操作系统不证明品牌提供该类独立部件或开发操作系统。'
                'offers只支持明确的产品提供关系，不能把导航分类或产品内含配置变成独立业务能力。')
        body = {'model': settings.llm_model, 'temperature': 0.1, 'max_tokens': 5500,
            'messages': [{'role': 'system', 'content': PROMPTS[task]+extra_rules},
                         {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]}
        if 'volces.com' in settings.llm_base_url:
            body['thinking'] = {'type': 'disabled'}
        async with httpx.AsyncClient(timeout=180, trust_env=False) as client:
            response = await client.post(settings.llm_base_url.rstrip('/')+'/chat/completions',
                headers={'Authorization': 'Bearer '+settings.llm_api_key}, json=body)
            if response.status_code >= 400:
                raise RuntimeError(f'Project LLM HTTP {response.status_code}')
            data = response.json()
        return data['choices'][0]['message']['content']
    scope = ChainScope(scope_id=stable_id('scope', subject, str(as_of)), subject=subject,
        as_of=str(as_of), geography='全球产业参与者；中国市场研究视角',
        assumptions=['行业全景，不推断企业之间实际供货关系'])
    request = ChainResearchRequest(run_id=run_id, scope=scope,
        research_strategy=research_strategy, profile_id=profile_id,
        budget=ResearchBudget(max_search_requests=12, max_document_fetches=32,
            max_llm_requests=34, max_wall_seconds=1200))
    if reverify_path is not None:
        from .service import reverify_bundle
        return await reverify_bundle(reverify_path, llm, ChainStore(run_dir), emit=emit)
    if resume_cache:
        from .profiles import resolve_profile
        expected = resolve_profile(scope, strategy=research_strategy, profile_id=profile_id)
        expected_strategy = 'profile_guided' if expected else 'explore'
        store = ChainStore(run_dir)
        cached = store.load_bundle()
        if (cached and cached.scope.model_dump() == scope.model_dump()
                and cached.manifest.research_strategy == expected_strategy
                and cached.manifest.profile_id == (expected.profile_id if expected else None)
                and cached.manifest.profile_version == (expected.version if expected else None)
                and cached.manifest.source_policy_version == 'doubao_v1'
                and cached.manifest.prompt_versions.get('research') == 'competition-profile-v1'):
            from .service import reverify_bundle
            return await reverify_bundle(store.v2_dir/'bundle.json', llm, store, emit=emit)
    service = ChainResearchService(search, DocumentFetchProvider(), llm, ChainStore(run_dir))
    return await service.research(request, emit=emit)
