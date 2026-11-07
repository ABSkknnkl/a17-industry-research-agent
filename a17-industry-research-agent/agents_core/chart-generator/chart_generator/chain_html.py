"""产业链图「LLM 排 HTML → chromium 截图」路径（2026-10-17）。

与项目既有的三条产出路径并列：

    ① 本地确定性 SVG   ``chain_render.render_chain_svg``     —— 兜底、可逐字审计
    ② AI 生图模型位图   ``image_gen.generate_industry_chain_image`` —— 默认关闭
    ③ **本模块**       LLM 把已过审的 ``ChainGraphSpec`` 排成 HTML 片段，
                        套我们的模板样式表后用项目自带 chromium 截图为 PNG

关键设计：**样式表是我们锁死的，模型只写结构化 body**。
第一版让模型连 CSS 一起写，真实调用在 90s 熔断线外 ReadTimeout（输出体量过大，
与 2026-10-07 否决「LLM 直出 SVG」的实测结论同源）。把 CSS 收回本模块后：
    - 输出 token 降到约 1/5，出图时长回到可接受区间；
    - 模板保真度由我们负责，模型改不动配色与版式常量（不会跑偏成别的风格）。

其它护栏：
    - 入口必须是已过 ``validate_topology`` / ``repair_topology`` 的 ChainGraphSpec，
      模型**不参与事实判断**，只负责把既定内容摆好看；
    - **漏项由代码补，不由模型赌**（``ensure_edge_labels``）：实测关掉思考后模型
      稳定漏掉配套带的连线标签（「数据反馈」「维护回收」）两次重试都不改，
      与其把交付押在模型自觉上，不如由代码按 spec 确定性补回 DOM；
    - 出图前后走与 SVG 完全同口径的文本级门禁（``lint_chain_texts`` / ``assert_text_fidelity``）；
    - 任一环节失败（LLM 不可用/超时/输出不合规/体检不过/截图失败）→ 返回 None，
      调用方回退 ① 的确定性 SVG，**图表不丢**。
"""
from __future__ import annotations

import asyncio
import html as _html_module
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── 画布常量（截图尺寸确定性：CSS 锁死画布宽度，否则每次出图尺寸漂移）──────────
CANVAS_WIDTH = 1440
DEVICE_SCALE = 2            # 2x 出图：PDF 内嵌与前端位图都不发虚
MIN_BODY_CHARS = 1200       # body 片段最小体量：低于此基本是半成品/缺整块内容
MAX_OUTPUT_CHARS = 64_000   # 失控生成熔断：实测过模型的 8.5MB/430s 重复吐字
MAX_OUTPUT_TOKENS = 8192    # 够用即可（合规片段约 2-3k token）；放太大会拖成数分钟
MAX_ATTEMPTS = 2            # 最多 2 次：第 2 次把缺失清单回灌给模型（关思考后单次 ~20s）
# 墙钟预算默认值。⚠️ 2026-10-17 实测：本项目的 predictive endpoint 生成约 3k token
# 需要 **370s**（首字节仅 1.4s，耗时全在推理），故默认给到 420s；想省时间可降此值，
# 超时即回退确定性 SVG，不会拖垮整条链路。用 ENABLE_INDUSTRY_CHAIN_HTML=0 可整体关闭。
DEFAULT_TIMEOUT_SECONDS = 420.0

_STAGE_LABEL = {
    "upstream": "上游",
    "midstream": "中游",
    "downstream": "下游",
    "support": "配套",
    "core": "核心本体",
    "other": "其他",
}

_FLOW_LABEL = {
    "material": "物料/零部件流",
    "technical": "技术/指令流",
    "service": "软件/服务流",
    "recycle": "逆向物流",
}


@dataclass
class GeneratedChainHtml:
    """HTML 出图结果。``image_path`` 为磁盘绝对路径（report-fusion 需读盘转 base64）。"""

    image_path: str
    image_uri: str
    html_path: str | None
    generation_prompt: str
    generation_prompt_model: str


# ─────────────────────────────────────────────────────────────────────────────
# 模板样式表（锁死，模型不可改）—— 取自人形机器人模板的视觉系统
# ─────────────────────────────────────────────────────────────────────────────
CHAIN_HTML_CSS = """
*{box-sizing:border-box;}
body{width:1440px;margin:0;padding:40px;background:#FFFFFF;
  font-family:system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;}
.page{width:100%;}
.title{font-size:32px;font-weight:700;color:#0F172A;margin:0;line-height:1.25;}
.subtitle{font-size:15px;color:#475569;margin:8px 0 0;line-height:1.5;}
.stats{font-size:13px;color:#94A3B8;margin:6px 0 0;text-align:right;}
.diagram{display:grid;grid-template-columns:320px 132px 300px 132px 380px 132px 320px;
  gap:0;margin-top:24px;align-items:start;}
.lane{display:flex;flex-direction:column;gap:14px;padding-top:4px;}
.gutter{display:flex;flex-direction:column;justify-content:center;gap:10px;height:100%;
  padding:60px 0;}
.flowtag{font-size:11px;color:#0E7490;background:#ECFEFF;border:1px solid #A5F3FC;
  border-radius:8px;padding:3px 6px;text-align:center;line-height:1.3;word-break:break-all;}
.pill{display:block;text-align:center;font-size:15px;font-weight:600;
  border-radius:999px;padding:9px 6px;border:1.4px solid;line-height:1.3;}
.pill-up{background:#EFF6FF;border-color:#2563EB;color:#2563EB;}
.pill-mid{background:#ECFEFF;border-color:#0891B2;color:#0891B2;}
.pill-core{background:#CFFAFE;border-color:#0E7490;color:#0E7490;}
.pill-down{background:#F5F3FF;border-color:#7C3AED;color:#7C3AED;}
.card{border-radius:12px;padding:11px 12px;border:1.2px solid;background:#FFFFFF;}
.card-up{border-color:#2563EB;background:#EFF6FF;}
.card-mid{border-color:#0891B2;background:#ECFEFF;}
.card-core{border-color:#0E7490;background:#CFFAFE;border-radius:18px;padding:16px;
  box-shadow:0 0 0 1px rgba(14,116,144,.35);}
.card-down{border-color:#7C3AED;background:#F5F3FF;}
.card.bottleneck{border-color:#EA580C;border-width:1.8px;background:#FFF7ED;}
.card.inferred{border-style:dashed;border-color:#94A3B8;background:#FFFFFF;}
.name{font-size:14px;font-weight:600;color:#0F172A;line-height:1.35;word-break:break-word;}
.comp{font-size:11px;color:#1D4ED8;margin-top:4px;line-height:1.45;word-break:break-word;}
.desc{font-size:10.5px;color:#475569;margin-top:4px;line-height:1.5;word-break:break-word;}
.badge{display:inline-block;font-size:9.5px;font-weight:600;border-radius:8px;
  padding:1px 6px;margin-left:6px;vertical-align:middle;line-height:1.5;}
.badge-hot{background:rgba(234,88,12,.12);border:.9px solid #EA580C;color:#EA580C;}
.badge-phase{background:rgba(124,58,237,.12);border:.8px solid #7C3AED;color:#6D28D9;}
.card.inferred .badge{background:rgba(148,163,184,.14);border:.8px solid #94A3B8;color:#64748B;}
.buyer{margin-top:7px;padding-top:6px;border-top:.8px solid rgba(124,58,237,.35);
  font-size:10.5px;color:#94A3B8;line-height:1.45;}
.brandlist{margin-top:8px;display:flex;flex-direction:column;gap:5px;}
.brand{font-size:13.5px;color:#0F172A;line-height:1.5;word-break:break-word;}
.brand::before{content:"● ";color:#0E7490;font-size:9px;}
.support{margin-top:30px;display:grid;grid-template-columns:repeat(3,1fr);gap:16px;}
.support-title{grid-column:1 / -1;font-size:13.5px;font-weight:600;color:#475569;margin:0;}
.sup{border:1.2px dashed #94A3B8;border-radius:12px;background:#F8FAFC;padding:12px 14px;}
.sup-title{font-size:14.5px;font-weight:600;color:#0F172A;line-height:1.4;}
.sup-body{font-size:10.5px;color:#94A3B8;margin-top:5px;line-height:1.5;word-break:break-word;}
.legend{margin-top:26px;font-size:12px;color:#475569;line-height:1.6;}
@media print{body{width:auto;padding:0;} .card,.sup{break-inside:avoid;}}
"""


def wrap_chain_html(body_html: str) -> str:
    """把模型产出的 body 片段套进我们锁定的模板外壳，得到完整自包含文档。"""
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        f"<style>{CHAIN_HTML_CSS}</style></head><body>{body_html.strip()}</body></html>"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 提示词
# ─────────────────────────────────────────────────────────────────────────────
CHAIN_HTML_SYSTEM = """你是产业研究报告的**信息图排版助手**，把给定的产业链数据排成 HTML 片段。

【输出格式】
只输出 `<body>` 内部的结构化 HTML 片段，**不要输出** <!doctype>/<html>/<head>/<style>/<script>，
不要解释文字、不要 Markdown 代码围栏。样式表已经写好并注入好了，**你只能使用下面的
class 名**，不许自定义 class、不许写 style 属性、不许内联颜色、不许用表格嵌套表格。

【可用 class】（照抄类名，不要自创）
- 版式骨架：`.page` `.title` `.subtitle` `.stats` `.diagram` `.lane` `.gutter` `.support` `.legend`
- 区域头（药丸）：`.pill` 配 `.pill-up`/`.pill-mid`/`.pill-core`/`.pill-down`
- 卡片：`.card` 配 `.card-up`/`.card-mid`/`.card-core`/`.card-down`，可叠加 `.bottleneck`/`.inferred`
- 卡片三行：`.name` `.comp` `.desc`
- 徽标：`.badge` `.badge-hot`（瓶颈橙）`.badge-phase`（落地阶段），采购方行 `.buyer`
- 本体品牌列表：`.brandlist` 内每行 `<div class="brand">品牌名</div>`
- 配套卡：`.sup` 内 `.sup-title` 与 `.sup-body`；区标题用 `.support-title`
- 连线标签：`.flowtag`（放在 gutter 里，一条边一个）

【版式约束】
1. `.page` 内依次写 `.title`、`.subtitle`、`.stats`（右上角小字，照抄 stats_line）。
2. 主体是一个 **七列** `.diagram`，必须按顺序写出七个子元素（缺任一列都会被判废）：
   `.lane`(上游) → `.gutter` → `.lane`(中游) → `.gutter` → `.lane`(核心本体) → `.gutter` → `.lane`(下游)
   三条 gutter 各有语义，按边的**起点区→终点区**归属放置，一条连线都不能丢：
   - gutter ①（上游|中游 之间）：源在上游的边（零部件/材料供给）
   - gutter ②（中游|核心 之间）：中游内部协作与算法/工具授权类边
   - gutter ③（核心|下游 之间）：整机交付/方案落地类边
   配套支撑类边（数据反馈/运维回收等）放在底部 `.support` 区标题之后。
   ⚠️ **`.flowtag` 的个数必须严格等于数据里 edges 的条数**，一条都不能漏——
   发完请自己数一遍（配套/逆向物流这类边最容易漏，已踩过两次）。
3. 每个 `.lane` 第一行是对应的 `.pill` 区域头，下面竖排若干 `.card`。
4. 每张 `.card` 必须三行齐全：`.name` 环节名、`.comp` 代表企业（用「 · 」连接；数据里没有
   就整行留空，**不要写"暂无"**）、`.desc` 一句话说明。
5. 瓶颈卡加 `.bottleneck`，`.name` 里追加 `<span class="badge badge-hot">瓶颈</span>`。
6. 推断卡（数据标了 inferred）加 `.inferred`，标题里追加 `<span class="badge">推断</span>`
   ——**底部配套卡同理**，缺了这个角标会被审计拦下（不给这个标记等于把无证据环节
   当成有证据环节，是口径事故）。
7. 下游卡在 `.desc` 之后追加落地阶段徽标与采购方行（数据里为空则省略），
   徽标写法：`<span class="badge badge-phase">这里填数据里的「落地阶段」原文</span>`
   ⚠️ **禁止把「阶段」两个字当内容抄进去**——必须填具体值（已落地 / 试点中 / 示范期 / 远期）；
   写成字面量「阶段」会被代码判废。采购方行：`<div class="buyer">采购方：数据里的采购方原文</div>`。
8. 核心本体卡 `.card-core`：`.name` + `.desc` + `.brandlist`（品牌**每个一行**用 `.brand`）。
9. 底部 `.support`：先一个 `.support-title`（写「配套 · 服务、软件与渠道（虚线挂接）」），
   再横排若干 `.sup` 卡（`.sup-title` 环节名 + `.sup-body` 说明 + 企业）。
10. 图末 `.legend` 一行：实线 = 物料 / 零部件流　虚线 = 数据 / 算法 / 服务流　橙框 = 卡脖子瓶颈环节

【内容硬约束】
11. **只能使用数据里给出的文字**，严禁补充任何企业名、产品名、市场结论。
12. **除「统计行」外禁止出现任何数字**；统计行必须**一字不差**照抄数据里的 stats_line
    （擅自另写一条统计行会被数值体检抓住）。
13. 禁止占位符与半截内容（XX / 示例 / 待补 / TODO / …）。
14. 数据里每个节点、每条连线都必须出现在页面上，**一个都不能丢**。
"""


def build_chain_html_payload(spec: Any, *, stats_line: str = "") -> str:
    """把 ChainGraphSpec 序列化成给模型的排版数据（只给事实，不给版式）。"""
    nodes = []
    for n in spec.nodes:
        nodes.append({
            "id": n.node_id,
            "区": _STAGE_LABEL.get(n.stage, n.stage),
            "环节名": n.name,
            "代表企业": list(n.companies or []),
            "细分产品": list(n.items or []),
            "说明": n.description or "",
            "是否核心本体": bool(n.is_core),
            "是否瓶颈": bool(n.bottleneck),
            "落地阶段": n.phase or "",
            "采购方": n.buyer or "",
            "缺证据是推断节点": bool(n.inferred),
        })
    name_of = {n.node_id: n.name for n in spec.nodes}
    edges = [
        {
            "起点": name_of.get(e.source, e.source),
            "终点": name_of.get(e.target, e.target),
            "标签": e.label or "",
            "流向": _FLOW_LABEL.get(e.flow, e.flow),
        }
        for e in spec.edges
    ]
    payload = {
        "title": spec.title,
        "subtitle": spec.subtitle or spec.core_product or "",
        "stats_line": stats_line,
        "stages": [{"id": s.stage_id, "title": s.title} for s in (spec.stages or [])],
        "nodes": nodes,
        "edges": edges,
    }
    return json.dumps(payload, ensure_ascii=False, indent=1)


def build_chain_html_prompt(spec: Any, *, stats_line: str = "") -> tuple[str, str]:
    """返回 (system_prompt, user_prompt)。"""
    labels = [str(e.label or "").strip() for e in (getattr(spec, "edges", None) or [])]
    labels = [l for l in labels if l]
    checklist = ""
    if labels:
        # 2026-10-17 实测：模型不看 edges 数组的长度，配套带边（数据反馈/运维回收）
        # 稳定漏排。把标签清单显式列出来让它照着清点数，能减少但**不能替代**代码补齐。
        checklist = (
            "\n\n【连线标签清点表】下面这 %d 个标签一个都不能少，必须各写一个 `.flowtag`：\n" % len(labels)
            + "、".join(f"「{l}」" for l in labels)
        )
    user = (
        "下面是这张产业链图必须呈现的全部数据（JSON）。请严格按系统提示的版式约束排 "
        "body 片段（只输出 body 内容，不要输出 <html>/<head>/<style>）：\n\n"
        + build_chain_html_payload(spec, stats_line=stats_line)
        + checklist
        + "\n\n再次提醒：节点与连线一个都不能少；除统计行外不得出现数字；"
        "`.diagram` 必须写满七列。"
    )
    return CHAIN_HTML_SYSTEM, user


# ─────────────────────────────────────────────────────────────────────────────
# HTML 抽取与门禁
# ─────────────────────────────────────────────────────────────────────────────
_FENCE_RE = re.compile(r"^```(?:html|xhtml)?\s*([\s\S]*?)\s*```$", re.IGNORECASE)


def strip_code_fence(raw: str) -> str:
    """模型常把片段包在 ```html 围栏里——剥掉，但不破坏片段内部文本。"""
    text = (raw or "").strip()
    m = _FENCE_RE.match(text)
    if m:
        return m.group(1).strip()
    if text.startswith("```html"):
        text = text[len("```html"):].strip()
    if text.endswith("```"):
        text = text[: -3].strip()
    return text


def html_texts(doc: str) -> list[str]:
    """抽取文档中的可见文本片段（用于与 SVG 同口径的文本级审计）。

    <script>/<style> 整块丢弃（前者是安全约束，后者是样式不是可读文案），
    其余标签之间的文本节点全部保留。
    """
    body = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", doc or "", flags=re.IGNORECASE)
    parts = re.split(r"<[^>]+>", body)
    out: list[str] = []
    for p in parts:
        p = _html_module.unescape(p).strip()
        if p:
            out.append(p)
    return out


def structural_issues(body_html: str) -> list[str]:
    """结构层体检：防止模型交出半张图 / 依赖外部资源 / 写脚本 / 漏掉七列骨架。"""
    errs: list[str] = []
    raw = body_html or ""
    low = raw.lower()
    if "<script" in low:
        errs.append("片段含 <script>，禁止脚本")
    if re.search(r"<link\b|@import|https?://|<style\b", low):
        errs.append("片段引用了外部资源或自带 <style>，样式表由系统注入")
    if len(raw) < MIN_BODY_CHARS:
        errs.append(f"片段体量过小（{len(raw)} 字符 < {MIN_BODY_CHARS}），疑似内容缺失")
    if '<div class="diagram"' not in raw and "class=\"diagram\"" not in raw:
        errs.append("缺少七列骨架 `.diagram`")
    # 2026-10-17 实测踩坑：模型把提示词示例里的「阶段」当成字面量抄进徽标，
    # 落地阶段等于没上图。这类"照抄占位符"必须机器拦，不能指望模型自觉。
    if re.search(r'badge-phase"[^>]*>\s*阶段\s*<', raw):
        errs.append("落地阶段徽标写成了字面量「阶段」，必须填数据里的具体值")
    return errs


def lint_chain_html(spec: Any, doc: str) -> list[dict[str, str]]:
    """HTML 路径的完整体检 = 结构层 + 文本层（与 SVG 同口径）。

    入参是**完整文档**（外壳 + 片段）；结构层只针对片段体，故这里取出片段后再查。
    """
    try:
        from chart_generator.chain_lint import lint_chain_texts
    except Exception:  # pragma: no cover  — 门禁不可用时宁可放行由上层兜底
        return []
    issues = [{"level": "error", "code": "html_structure", "message": m}
              for m in structural_issues(_body_of(doc))]
    issues.extend(lint_chain_texts(spec, html_texts(doc)))
    return issues


def _body_of(doc: str) -> str:
    """取 <body> 内部片段；取不到就当整串都是片段。"""
    m = re.search(r"<body[^>]*>([\s\S]*)</body>", doc or "", flags=re.IGNORECASE)
    return m.group(1) if m else (doc or "")


def assert_html_fidelity(spec: Any, doc: str) -> list[str]:
    """事实锁死：节点名/企业名/连线标签必须逐字出现在页面上（空 = 通过）。

    2026-10-21：``omit_unrendered_edges=False``。HTML 版式**画连线**（``.flowtag``），
    它的提示词写着"标签个数必须严格等于 edges 条数"。SVG 目录式不画连线才豁免标签，
    这条豁免不能顺延到 HTML，否则 `ensure_edge_labels` 的补漏逻辑永远不会被触发。
    """
    try:
        from chart_generator.chain_lint import assert_text_fidelity
    except Exception:  # pragma: no cover
        return []
    return assert_text_fidelity(spec, "".join(html_texts(doc)),
                                omit_unrendered_edges=False)


# ─────────────────────────────────────────────────────────────────────────────
# 确定性补齐：模型漏写的连线标签由代码补回 DOM
# ─────────────────────────────────────────────────────────────────────────────
_LANE_ORDER = ("upstream", "midstream", "core", "downstream")

_DIV_OPEN_RE = re.compile(r"<div\b")
_DIV_CLOSE_RE = re.compile(r"</div\s*>")


def _div_block_spans(html: str, class_name: str) -> list[tuple[int, int]]:
    """找出所有带指定 class 的 div 块，返回 [(块起点, 闭合标签起点)]。

    手工扫 div 深度而不上解析器：模型产出的片段允许任意嵌套与换行，
    但只要 div 是配对的就能定位；解析失败时返回空，调用方降级为"不补"。
    """
    spans: list[tuple[int, int]] = []
    pattern = re.compile(r'<div[^>]*class="[^"]*\b' + re.escape(class_name) + r'\b[^"]*"[^>]*>')
    for m in pattern.finditer(html or ""):
        depth = 1
        pos = m.end()
        while depth:
            nxt_open = _DIV_OPEN_RE.search(html, pos)
            nxt_close = _DIV_CLOSE_RE.search(html, pos)
            if not nxt_close:
                break
            if nxt_open and nxt_open.start() < nxt_close.start():
                depth += 1
                pos = nxt_open.end()
            else:
                depth -= 1
                pos = nxt_close.end()
                if depth == 0:
                    spans.append((m.start(), nxt_close.start()))
    return spans


def _span_text(html: str, span: tuple[int, int]) -> str:
    return "".join(html_texts(html[span[0]: span[1]]))


def _support_insert_point(
    body: str,
    sup_spans: list[tuple[int, int]],
    support_span: tuple[int, int] | None,
    source_name: str,
) -> int | None:
    """配套带边的落点：优先挂在**起点配套卡**末尾，找不到就挂到配套区末尾。"""
    for span in sup_spans:
        if source_name and source_name[:6] in _span_text(body, span):
            return span[1]
    return support_span[1] if support_span else None


def ensure_edge_labels(body_html: str, spec: Any) -> tuple[str, list[str]]:
    """把模型漏掉的连线标签按 spec 确定性补回片段。返回 (片段, 补回的标签列表)。

    设计取舍（2026-10-17 实测）：关掉思考后模型**稳定**漏掉配套带的两条边
    （「数据反馈」「维护回收」），带缺失清单重试一次仍然漏。环节标签凭空消失是
    口径事故，不能靠"再试一次"赌，所以改由代码按 spec 补：

        · 主带边 → 按起点/终点所在泳道的相邻 gutter 追加；
        · 配套带边 → 追加到起点配套卡末尾（找不到就放配套区末尾）。

    只补**连线标签**这一项事实；结构层/文本层体检问题一律不掩盖，仍走重试或回退。
    """
    blob = "".join(html_texts(body_html))
    # 🔴 2026-10-21：不再套 `_omitted_edge_labels`。那条豁免是给 SVG 三列目录式用的
    # （卡片之间零连线，标签本就不画）。HTML 版式**画连线**，没有"有意省略"一说，
    # 套用豁免会让补漏逻辑永远拿到空 todo —— 实测两条用例直接红。
    todo = [
        e for e in (getattr(spec, "edges", None) or [])
        if e.label and e.label not in blob
    ]
    if not todo:
        return body_html, []

    stage_of = {n.node_id: str(n.stage or "") for n in spec.nodes}
    name_of = {n.node_id: n.name for n in spec.nodes}
    gutters = _div_block_spans(body_html, "gutter")
    sups = _div_block_spans(body_html, "sup")
    support_blocks = _div_block_spans(body_html, "support")
    support_span = support_blocks[0] if support_blocks else None

    plan: list[tuple[int, str]] = []
    for e in todo:
        ss, ts = stage_of.get(e.source, ""), stage_of.get(e.target, "")
        if ss not in _LANE_ORDER or ts not in _LANE_ORDER:
            idx = _support_insert_point(body_html, sups, support_span, name_of.get(e.source, ""))
        else:
            gi = max(0, min(len(gutters) - 1, min(_LANE_ORDER.index(ss), _LANE_ORDER.index(ts))))
            idx = gutters[gi][1] if gutters else None
        if idx is None:
            continue
        plan.append((idx, e.label))
    if not plan:
        return body_html, []

    by_idx: dict[int, list[str]] = {}
    for idx, label in plan:
        by_idx.setdefault(idx, []).append(label)
    out = body_html
    for idx in sorted(by_idx, reverse=True):
        block = "".join(
            f'<div class="flowtag">{_html_module.escape(l)}</div>' for l in by_idx[idx]
        )
        out = out[:idx] + block + out[idx:]
    return out, [l for _, l in plan]


# ─────────────────────────────────────────────────────────────────────────────
# LLM 调用 + 截图
# ─────────────────────────────────────────────────────────────────────────────
def build_html_llm_payload(
    *,
    system_prompt: str,
    user_prompt: str,
    model: str,
    max_tokens: int = MAX_OUTPUT_TOKENS,
    thinking: str = "disabled",
) -> dict[str, Any]:
    """构造 chat/completions 请求体（抽成纯函数便于直接断言，无需 mock 网络）。"""
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": min(int(max_tokens), MAX_OUTPUT_TOKENS),
        "stream": True,
    }
    if thinking:
        payload["thinking"] = {"type": thinking}
    return payload


async def call_html_llm(
    *,
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    base_url: str,
    model: str,
    timeout_seconds: float,
    max_tokens: int = MAX_OUTPUT_TOKENS,
    thinking: str = "disabled",
) -> tuple[str, str]:
    """调用项目大模型产出 HTML 片段。返回 (片段, model_name)。失败抛异常由上层兜底。

    **必须流式**：实测延迟全部发生在生成阶段——同样的提示词非流式调用会在 90s
    httpx 读超时上 ReadTimeout，而流式 1.4s 即首字节、`finish_reason=stop` 大约在
    370s（2026-10-17 实测）。
    因此这里用三道闸：``max_tokens`` 上限 + 字节上限（防失控重复生成）+ 外层墙钟预算。

    ``thinking="disabled"``（默认）：该端点开启思考时生成慢一个量级，实测同等任务
    10.4s → 5.8s（关闭后），长任务差距更大，故默认关掉。
    """
    import httpx

    base = (base_url or "").rstrip("/")
    payload = build_html_llm_payload(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        max_tokens=max_tokens,
        thinking=thinking,
    )

    async def _read() -> str:
        buf: list[str] = []
        size = 0
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            ) as res:
                res.raise_for_status()
                async for line in res.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        data = json.loads(chunk)
                    except ValueError:
                        continue
                    for choice in data.get("choices") or []:
                        delta = (choice.get("delta") or {}).get("content") or ""
                        if delta:
                            buf.append(delta)
                            size += len(delta)
                        if choice.get("finish_reason"):
                            return "".join(buf)
                    if size > MAX_OUTPUT_CHARS:
                        # 失控重复生成：8.5MB/430s 的实测教训，宁可截断走下一轮门禁
                        logger.warning(
                            "产业链 HTML 出图触字节上限（>%d 字符），判定为失控生成并截断",
                            MAX_OUTPUT_CHARS,
                        )
                        return "".join(buf)
        return "".join(buf)

    body = strip_code_fence(await asyncio.wait_for(_read(), timeout=timeout_seconds))
    if len(body) < MIN_BODY_CHARS:
        raise ValueError(f"模型输出的 HTML 片段过短：{len(body)} 字符")
    return body, model


async def render_html_to_png(
    doc: str,
    out_path: Path,
    *,
    width: int = CANVAS_WIDTH,
    scale: int = DEVICE_SCALE,
    timeout_seconds: float = 60.0,
) -> int:
    """用项目自带的 chromium 把完整文档截成 PNG。返回图片字节数。

    走 async API：调用方处在 FastAPI/状态机的事件循环里，同步 playwright 会阻塞整个循环。
    """
    from playwright.async_api import async_playwright

    async def work() -> int:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page(
                    viewport={"width": width, "height": 1000},
                    device_scale_factor=scale,
                )
                await page.set_content(doc, wait_until="load")
                try:
                    await page.evaluate("document.fonts && document.fonts.ready")
                except Exception:
                    pass
                await page.screenshot(path=str(out_path), full_page=True)
            finally:
                await browser.close()
        return out_path.stat().st_size

    return int(await asyncio.wait_for(work(), timeout=timeout_seconds))


async def generate_chain_html_image(
    spec: Any,
    *,
    settings: Any,
    artifact_dir: Path | None,
    chart_id: str,
    stats_line: str = "",
) -> GeneratedChainHtml | None:
    """产业链图 HTML 直出的完整编排。任何一步失败都返回 None（调用方回退确定性 SVG）。"""
    if not (getattr(settings, "llm_api_key", "") and getattr(settings, "llm_model", "")):
        logger.warning("产业链 HTML 出图跳过：未配置 LLM_API_KEY / LLM_MODEL，回退确定性 SVG")
        return None

    timeout_limit = min(
        float(getattr(settings, "llm_timeout_seconds", 60.0)),
        float(os.getenv("CHAIN_HTML_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))),
    )
    system_prompt, base_user_prompt = build_chain_html_prompt(spec, stats_line=stats_line)
    user_prompt = base_user_prompt
    used_model = str(getattr(settings, "llm_model", ""))

    # 2026-10-17：关掉思考后单次调用仅 ~20s，允许**一次带反馈的重试**——
    # 把门禁判出的缺失清单原样回灌给模型（实测配套/逆向物流类边最易漏）。
    doc = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            body_html, used_model = await call_html_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                model=settings.llm_model,
                timeout_seconds=timeout_limit,
                max_tokens=int(getattr(settings, "llm_max_tokens", 16384)),
                thinking=str(getattr(settings, "llm_thinking", "disabled") or "disabled"),
            )
        except asyncio.TimeoutError:
            logger.warning("产业链 HTML 出图超时（>%.0fs），回退确定性 SVG", timeout_limit)
            return None
        except Exception as exc:
            logger.warning("产业链 HTML 出图调用失败，回退确定性 SVG：%s", type(exc).__name__)
            return None

        doc = wrap_chain_html(body_html)
        # ── 产物级体检：结构 + 文本（与 SVG 同口径）──
        issues = lint_chain_html(spec, doc)
        missing = assert_html_fidelity(spec, doc)
        if not (issues or missing):
            break
        # ── 仅当"体检没毛病、只是漏了连线标签"时由代码补齐（不掩盖任何体检问题）──
        if missing and not issues:
            patched, injected = ensure_edge_labels(body_html, spec)
            if injected:
                fixed = wrap_chain_html(patched)
                if not assert_html_fidelity(spec, fixed) and not lint_chain_html(spec, fixed):
                    logger.warning(
                        "产业链 HTML 出图：模型漏写 %d 条连线标签，已由代码确定性补齐 → %s",
                        len(injected), injected,
                    )
                    doc = fixed
                    break
        if artifact_dir:
            try:
                bad = artifact_dir / "charts" / f"{chart_id}.rejected{attempt}.html"
                bad.parent.mkdir(parents=True, exist_ok=True)
                bad.write_text(doc, encoding="utf-8")
            except Exception:
                pass
        logger.warning(
            "产业链 HTML 第 %d 次出图未过门禁：%d 项体检问题 / %d 项事实缺失",
            attempt, len(issues), len(missing),
        )
        logger.warning("  体检：%s", [i["message"] for i in issues[:3]] or "[]")
        logger.warning("  缺失：%s", missing[:5] or "[]")
        if attempt == MAX_ATTEMPTS:
            logger.warning("产业链 HTML 出图重试后仍未过门禁，回退确定性 SVG")
            return None
        user_prompt = base_user_prompt + "\n\n【上一版被门禁判废，必须修正后再输出】\n" + "\n".join(
            [f"- 问题：{i['message']}" for i in issues[:6]]
            + [f"- 缺失：{m}" for m in missing[:12]]
        )

    if artifact_dir:
        html_path = artifact_dir / "charts" / f"{chart_id}.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        out_dir = artifact_dir / "images"
        out_dir.mkdir(parents=True, exist_ok=True)
        png_path = out_dir / f"{chart_id}_chain.png"
    else:
        # 无落盘目录（后端 save_artifacts=False 的常态）：写到临时目录，但**HTML 也照写**。
        # 少了它，调用方只拿到一张 PNG、无法回溯"这张图到底是用哪版 HTML 截的"；
        # 后端适配层会把这两个文件搬进正式产物目录。
        import tempfile

        tmp_dir = Path(tempfile.mkdtemp(prefix="chain_html_"))
        html_path = tmp_dir / f"{chart_id}.html"
        png_path = tmp_dir / f"{chart_id}_chain.png"
    html_path.write_text(doc, encoding="utf-8")
    image_path = str(png_path)

    try:
        size = await render_html_to_png(
            doc, png_path,
            timeout_seconds=float(os.getenv("CHAIN_HTML_SHOT_TIMEOUT", "60.0")),
        )
    except asyncio.TimeoutError:
        logger.warning("产业链 HTML 截图超时，回退确定性 SVG")
        return None
    except Exception as exc:
        logger.warning("产业链 HTML 截图失败，回退确定性 SVG：%s", type(exc).__name__)
        return None
    if size < 20_000:
        logger.warning("产业链 HTML 截图异常偏小（%d bytes），回退确定性 SVG", size)
        return None

    logger.info("产业链 HTML 出图成功（Agent3）：%s（%s bytes）", image_path, f"{size:,}")
    return GeneratedChainHtml(
        image_path=image_path,
        image_uri=image_path,
        html_path=str(html_path) if html_path else None,
        generation_prompt=user_prompt,
        generation_prompt_model=used_model,
    )
