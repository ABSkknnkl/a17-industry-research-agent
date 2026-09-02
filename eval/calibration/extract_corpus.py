"""券商研报 PDF → 评审器校准语料抽取管线。

对应《评审器调优与红蓝对抗方案.md》§1 阶段一「数据基建」。

管线四步：
    extract（按坐标聚行，剔除页眉页脚/图表题注/目录）
      → merge（相邻残段合并，修复跨行跨栏断裂）
      → curate（合规脱敏 + 完整性 + 可读性过滤）
      → select（按语体配额 + 难度分层抽样）

用法：
    # 需要 pymupdf（pdfkit skill 的 venv 内有，或自行 pip install pymupdf）
    python extract_corpus.py extract  <pdf目录> <输出.json>
    python extract_corpus.py merge    <池.json> <输出.json>
    python extract_corpus.py curate   <池.json> <输出.json>
    python extract_corpus.py select   <候选.json> <输出.json>
    python extract_corpus.py lintstats <候选.json>   # Linter 误杀率体检

设计约束：
- 合规脱敏是硬要求：真实研报含个股推荐/评级/目标价，直接当正例会教坏模型，
  必须在 curate 阶段剔除（对应 prompt.md 金融内容红线）。
- 本脚本只产出「候选」，gold_label 必须人工标注（方案 §1.4：
  judge 的正误标准必须来自人，否则是自己考自己）。
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    import pymupdf
except ImportError:  # pragma: no cover
    pymupdf = None  # type: ignore[assignment]

# ============================================================ 过滤规则
NOISE_LINE = (
    re.compile(r"请仔细阅读在本报告尾部的重要法律声明"),
    re.compile(r"^(行业研究|公司研究|策略研究|深度研究|证券研究报告)$"),
    re.compile(r"^\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日$"),
    re.compile(r"^资料来源[:：]"),
    re.compile(r"^(图表|图|表)\s*\d+"),
    re.compile(r"^(免责声明|分析师声明|评级说明|投资评级说明|重要声明|法律声明|"
               r"本公司具备证券投资咨询|风险提示及免责)"),
    re.compile(r"^(证券分析师|执业证书编号|研究助理|联系人|电话[:：]|邮箱[:：])"),
    re.compile(r"^(优于大市|中性|弱于大市|买入|增持)$"),
)
TOC_DOTS = re.compile(r"(\.\s*){6,}|\.{6,}")
TABLE_ROW = re.compile(r"^[\d\s\.,%\-+()（）/：:；;×~＜><=]*$")

MIN_CHARS, MAX_CHARS = 30, 500
MIN_CN_RATIO = 0.55
HEADER_RATIO = FOOTER_RATIO = 0.08
LINE_GAP_FACTOR = 1.6
TERMINAL = re.compile(r"[。！？」』\"）)]$")

# ============================================================ 合规红线
RED_LINE = re.compile(
    r"推荐[:：]|个股推荐|目标价|目标市值|投资评级|强于大市|弱于大市|优于大市"
    r"|首次覆盖|买入评级|增持评级|\d{6}\.(SZ|SH|HK|BJ)|仓位建议|择时"
)
LEGAL = re.compile(
    r"免责声明|分析师声明|执业证书|研究助理|证券分析师|投资评级说明"
    r"|本报告由|未经.*书面授权|法律责任"
)
DISCLAIMER_PHRASE = re.compile(
    r"仅供本公司客户参考|不构成所述证券|不构成对任何人的个人推荐"
    r"|独立评估|本报告中的信息"
)
# 个股推荐暗示 / 证券排序（同为红线）
STOCK_PITCH = re.compile(r"建议(积极|持续|重点)?关注|建议配置|重点推荐|首推")
STOCK_RANK = re.compile(r"涨幅居前|跌幅居前|涨幅排名|跌幅排名|涨幅前[五三五十\d]|跌幅前[五三五十\d]")

# ============================================================ 完整性
ENDS_OK = re.compile(r"[。！？]$")
STARTS_BAD = re.compile(r"^[，。；、）)\]】%．,;:：]|^[a-z]{1,3}[\s，。]")
HEADING_NUM_GLUE = re.compile(r"^\d+(\.\d+)*\S")
HEADING_GLUE = re.compile(r"^[^。：:]{2,28}[：:]\S")
FRAGMENT_START = re.compile(
    r"^[\u4e00-\u9fa5]{1,2}(也|凭借|在|将|的|是|并|及|其|已|正|又|则)[，、]"
)
CONNECTIVE_START = re.compile(r"^(求|厚|场|能|会|有|为|对|从|以|使|让|与|和|或)[，、]")
MID_HEADING = re.compile(r"(?<=\S)\d{1,2}\.\d{1,2}[\u4e00-\u9fa5]")
SENT_SPLIT = re.compile(r"[。！？；!?]")

# ============================================================ 语体配额
GENRE: dict[str, tuple[str, int]] = {}
LONG_SENT_MIN = 45
MAX_JOIN = 3


def clean(text: str) -> str:
    """清理 PDF 排版引入的中文/数字间异常空格。"""
    text = text.strip()
    text = re.sub(r"(?<=[\u4e00-\u9fa5])\s+(?=[\u4e00-\u9fa5])", "", text)
    text = re.sub(r"(?<=\d)\s+(?=[\u4e00-\u9fa5%℃])", "", text)
    text = re.sub(r"(?<=[\u4e00-\u9fa5%℃])\s+(?=\d)", "", text)
    text = re.sub(r"(?<=\d)\s+(?=\d)", "", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def is_noise(text: str) -> bool:
    return bool(TOC_DOTS.search(text)) or any(p.search(text) for p in NOISE_LINE)


def sentence_lengths(text: str) -> list[int]:
    return [len(s.strip()) for s in SENT_SPLIT.split(text) if s.strip()]


# ---------------------------------------------------------- extract
def page_paragraphs(page) -> list[str]:
    h = page.rect.height
    top, bottom = h * HEADER_RATIO, h * (1 - FOOTER_RATIO)
    lines: list[dict] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            y0 = min(s["bbox"][1] for s in spans)
            y1 = max(s["bbox"][3] for s in spans)
            x0 = min(s["bbox"][0] for s in spans)
            if y1 < top or y0 > bottom:
                continue
            txt = clean("".join(s["text"] for s in spans))
            if txt:
                lines.append({"y0": y0, "y1": y1, "x0": x0, "text": txt})

    lines.sort(key=lambda L: (round(L["y0"] / 3), L["x0"]))
    paras: list[str] = []
    buf: list[dict] = []
    for line in lines:
        if is_noise(line["text"]):
            if buf:
                paras.append("".join(b["text"] for b in buf))
                buf = []
            continue
        if buf:
            prev = buf[-1]
            height = max(prev["y1"] - prev["y0"], 1.0)
            gap = line["y0"] - prev["y1"]
            if gap > height * LINE_GAP_FACTOR or abs(line["x0"] - prev["x0"]) >= 12:
                paras.append("".join(b["text"] for b in buf))
                buf = []
        buf.append(line)
    if buf:
        paras.append("".join(b["text"] for b in buf))
    return paras


def cmd_extract(pdf_dir: Path, out: Path) -> None:
    if pymupdf is None:
        raise SystemExit("需要 pymupdf：pip install pymupdf")
    files = sorted(list(pdf_dir.glob("*.pdf")) + list(pdf_dir.glob("*.PDF")))
    if not files:
        raise SystemExit(f"未找到 PDF：{pdf_dir}")
    allp: list[dict] = []
    for f in files:
        doc = pymupdf.open(f)
        seen: set[str] = set()
        stop = False
        for idx, page in enumerate(doc, start=1):
            if stop:
                break
            for para in page_paragraphs(page):
                if re.match(r"^(免责声明|分析师声明|评级说明|重要声明|法律声明)", para):
                    stop = True
                    break
                if not (MIN_CHARS <= len(para) <= MAX_CHARS):
                    continue
                if TABLE_ROW.match(para):
                    continue
                cn = len(re.findall(r"[\u4e00-\u9fa5]", para))
                if cn / len(para) < MIN_CN_RATIO or para in seen:
                    continue
                seen.add(para)
                allp.append({"source_file": f.name, "page": str(idx), "text": para})
        doc.close()
        print(f"  {f.name}: {sum(1 for p in allp if p['source_file'] == f.name)} 段")
    out.write_text(json.dumps(allp, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"extract → {len(allp)} 段 -> {out}")


# ---------------------------------------------------------- merge
def cmd_merge(src: Path, out: Path) -> None:
    paras = json.loads(src.read_text(encoding="utf-8"))
    merged: list[dict] = []
    buf: dict | None = None
    pending: list[dict] = []

    def flush() -> None:
        nonlocal buf
        if buf is None:
            return
        if pending:
            buf = {**buf, "text": buf["text"] + "".join(p["text"] for p in pending)}
            pending.clear()
        merged.append(buf)
        buf = None

    for p in paras:
        if buf is not None and not TERMINAL.search(buf["text"]):
            if (p["source_file"] == buf["source_file"]
                    and abs(int(p["page"]) - int(buf["page"])) <= 1
                    and len(pending) < MAX_JOIN):
                pending.append(p)
                continue
            flush()
        flush()
        buf = p
    flush()

    out_list: list[dict] = []
    for p in merged:
        if len(p["text"]) > 500:
            parts, cur = [], ""
            for ch in p["text"]:
                cur += ch
                if ch in "。！？" and len(cur) >= 60:
                    parts.append(cur)
                    cur = ""
            if cur:
                parts.append(cur)
            out_list.extend({**p, "text": t} for t in parts)
        else:
            out_list.append(p)

    term = sum(1 for p in out_list if TERMINAL.search(p["text"]))
    print(f"merge: {len(paras)} → {len(out_list)}，句末完整率 {term/len(out_list):.0%}")
    out.write_text(json.dumps(out_list, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {out}")


# ---------------------------------------------------------- curate
def is_clean(text: str) -> tuple[bool, str]:
    if RED_LINE.search(text):
        return False, "红线内容（个股推荐/评级/目标价）"
    if STOCK_PITCH.search(text):
        return False, "个股推荐暗示（建议关注类）"
    if STOCK_RANK.search(text):
        return False, "个股涨跌排名（证券排序红线）"
    if LEGAL.search(text) or DISCLAIMER_PHRASE.search(text):
        return False, "法律/免责声明残留"
    if not ENDS_OK.search(text):
        return False, "结尾截断"
    if STARTS_BAD.match(text):
        return False, "开头截断"
    sents = sentence_lengths(text)
    if not sents:
        return False, "无完整句"
    if max(sents) > 120:
        return False, "含超长残句(>120字)"
    if sents[0] < 14:
        return False, "开头截断（首句<14字）"
    if HEADING_NUM_GLUE.match(text):
        return False, "标题编号粘连"
    if HEADING_GLUE.match(text) and re.search(r"(我们认为|预计|根据|数据显示|同比|环比)", text):
        return False, "标题与正文粘连"
    for m in MID_HEADING.finditer(text):
        if m.start() > 5:
            return False, "句中夹带标题编号（跨段误合并）"
    if FRAGMENT_START.match(text) or CONNECTIVE_START.match(text):
        return False, "残句开头"
    if len(re.findall(r"[\d\.%]", text)) / len(text) > 0.35:
        return False, "数字密度过高（疑似表格残留）"
    return True, ""


def cmd_curate(src: Path, out: Path) -> None:
    paras = json.loads(src.read_text(encoding="utf-8"))
    kept, dropped, reasons = [], [], Counter()
    for p in paras:
        ok, why = is_clean(p["text"])
        if ok:
            sents = sentence_lengths(p["text"])
            p = {**p,
                 "max_sent_len": max(sents),
                 "avg_sent_len": round(sum(sents) / len(sents), 1),
                 "char_len": len(p["text"])}
            kept.append(p)
        else:
            reasons[why] += 1
            dropped.append({**p, "drop_reason": why})

    print(f"curate: {len(paras)} → 保留 {len(kept)} / 剔除 {len(dropped)}")
    for why, n in reasons.most_common():
        print(f"    {why}: {n}")
    long_s = sum(1 for p in kept if p["max_sent_len"] > LONG_SENT_MIN)
    print(f"    长句边界样本(>{LONG_SENT_MIN}字): {long_s}")
    out.write_text(json.dumps(kept, ensure_ascii=False, indent=1), encoding="utf-8")
    out.with_suffix(".dropped.json").write_text(
        json.dumps(dropped, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"→ {out}")


# ---------------------------------------------------------- select
def quality_score(text: str) -> float:
    s = 0.0
    if re.search(r"(我们认为|预计|判断|表明|意味着|显示|得益于|受.{0,6}驱动)", text):
        s += 2
    if re.search(r"\d", text):
        s += 1
    if re.search(r"(因此|所以|由于|因为|同时|此外|但|然而|进而)", text):
        s += 1
    if re.search(r"(但|然而|不过|风险|不确定性|需关注|有待验证)", text):
        s += 1.5
    if len(text) < 45:
        s -= 2
    return s


def cmd_select(src: Path, out: Path) -> None:
    cand = json.loads(src.read_text(encoding="utf-8"))
    by_file: dict[str, list[dict]] = defaultdict(list)
    for p in cand:
        by_file[p["source_file"]].append(p)

    selected: list[dict] = []
    for fname, (genre, quota) in GENRE.items():
        pool = by_file.get(fname, [])
        long_pool = sorted(
            [p for p in pool if p["max_sent_len"] > LONG_SENT_MIN],
            key=lambda p: quality_score(p["text"]), reverse=True)
        short_pool = sorted(
            [p for p in pool if p["max_sent_len"] <= LONG_SENT_MIN],
            key=lambda p: quality_score(p["text"]), reverse=True)
        take_long = min(len(long_pool), quota // 2 + quota % 2)
        picked = long_pool[:take_long] + short_pool[: quota - take_long]
        if len(picked) < quota:
            picked += (long_pool[take_long:] + short_pool[quota - take_long:])[
                : quota - len(picked)]
        for p in picked:
            selected.append({**p, "genre": genre,
                             "quality_score": round(quality_score(p["text"]), 1)})

    print(f"select: {len(selected)} 条")
    for g, n in Counter(p["genre"] for p in selected).most_common():
        print(f"    {g}: {n}")
    out.write_text(json.dumps(selected, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {out}")


# ---------------------------------------------------------- lintstats
def cmd_lintstats(src: Path) -> None:
    """用现行 ReadabilityLinter 体检候选池，量化误杀率。"""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
    from app.agents.chapter_writer.readability_linter import (  # noqa: PLC0415
        lint_paragraph,
    )
    paras = json.loads(src.read_text(encoding="utf-8"))
    rules: Counter = Counter()
    flagged = 0
    for p in paras:
        fs = lint_paragraph(p["text"])
        if fs:
            flagged += 1
            for f in fs:
                rules[f.rule_id] += 1
    print(f"Linter 命中 {flagged}/{len(paras)} = {flagged/len(paras):.1%}（真实研报误杀率）")
    for k, v in rules.most_common():
        print(f"    {k}: {v}")


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    cmd, a = sys.argv[1], Path(sys.argv[2])
    b = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    if cmd == "extract":
        cmd_extract(a, b)
    elif cmd == "merge":
        cmd_merge(a, b)
    elif cmd == "curate":
        cmd_curate(a, b)
    elif cmd == "select":
        if not GENRE:
            raise SystemExit(
                "select 前需在脚本顶部 GENRE 配置语体配额：{文件名: (语体, 配额)}"
            )
        cmd_select(a, b)
    elif cmd == "lintstats":
        cmd_lintstats(a)
    else:
        raise SystemExit(f"未知命令：{cmd}")


if __name__ == "__main__":
    main()
