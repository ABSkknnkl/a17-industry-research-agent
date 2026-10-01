"""把「阶段3 图表」预置进 run-20260926203242-178（录演示视频用，跳过真实生成）。

做了什么：
1. 把用户提供的产业链图放进该 run 的 artifacts/，作为 CHART-01 的 AI 生成图；
2. 从同主题已跑完的 run-20260926022235-107 移植其余 15 张图（SVG + JSON + spec）；
3. 生成 chart_result.json（阶段4「章节生成」硬依赖它，缺了会直接报错）；
4. 把阶段2/阶段3 标为 approved、current_stage 推进到 chapter_write —— 
   这样 resume_run 的「第一个未完成阶段」定位会直接落在阶段4，**不会重跑阶段3 覆盖预置**。

幂等：可重复执行（每次都从源 run 重新取数据）。执行前自动备份 state.json。
"""
import json
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path("/Users/Zhuanz1/Downloads/行业研究智能体-全链路系统 4")
RUNS = ROOT / "data/runs"
TARGET_RID = "run-20260926203242-178"   # 待预置的 run（已完成阶段1、2）
SOURCE_RID = "run-20260926022235-107"  # 同主题已跑完阶段3 的 run（低空经济）
CHAIN_IMAGE = Path(
    "/Users/Zhuanz1/.workbuddy/clipboard-images/"
    "clipboard-2026-09-26T12-56-30-049Z-00a0ca35.jpg"
)

target = RUNS / TARGET_RID
source = RUNS / SOURCE_RID
t_art = target / "artifacts"
s_art = source / "artifacts"

# ── 0. 前置校验 ──────────────────────────────────────────────────────
for p in (target / "state.json", source / "state.json", CHAIN_IMAGE,
          s_art / "chart_result.json"):
    if not p.exists():
        raise SystemExit(f"缺少必要文件: {p}")
if not (s_art / "charts").is_dir():
    raise SystemExit(f"缺少源图表目录: {s_art / 'charts'}")

# ── 1. 备份 state.json ───────────────────────────────────────────────
stamp = datetime.now().strftime("%Y%m%d%H%M%S")
backup = target / f"state.json.bak-{stamp}"
shutil.copy2(target / "state.json", backup)
print(f"已备份 state.json → {backup.name}")

# ── 2. 产业链图放进 artifacts/ ────────────────────────────────────────
# 命名不带路径分隔符，且全局唯一，保证 storage.get_artifact_path 的
# 「artifacts 根目录按文件名匹配」能命中；前端 image_uri 以 / 开头会直接当 src 用。
chain_name = "CHAIN-01-lowaltitude.jpg"
t_art.mkdir(parents=True, exist_ok=True)
shutil.copy2(CHAIN_IMAGE, t_art / chain_name)
print(f"产业链图已放入 artifacts/{chain_name} ({CHAIN_IMAGE.stat().st_size:,} bytes)")

# ── 3. 移植 15 张图的矢量产物 ────────────────────────────────────────
t_charts = t_art / "charts"
t_charts.mkdir(parents=True, exist_ok=True)
count = 0
for f in sorted((s_art / "charts").iterdir()):
    if f.is_file() and f.suffix.lower() in (".svg", ".json"):
        shutil.copy2(f, t_charts / f.name)
        count += 1
print(f"已移植图表产物 {count} 个 → artifacts/charts/")

# ── 4. 读取源阶段3 数据并改写（路径 107 → 178） ───────────────────────
src_state = json.loads((source / "state.json").read_text(encoding="utf-8"))
src_cg = src_state["stage_results"]["chart_generate"]
chart_data = json.loads(json.dumps(src_cg["data"], ensure_ascii=False))


def repath(value):
    """把产物里的绝对路径从源 run 改写到目标 run。

    注意：本函数返回**新对象**，所以必须在它之后重新取 specs，
    否则后续对 specs 的原地修改会作用在旧对象上、写不回 chart_data。
    """
    if isinstance(value, str):
        return value.replace(f"/runs/{SOURCE_RID}/", f"/runs/{TARGET_RID}/")
    if isinstance(value, list):
        return [repath(v) for v in value]
    if isinstance(value, dict):
        return {k: repath(v) for k, v in value.items()}
    return value


chart_data = repath(chart_data)
specs = chart_data.get("chart_specs") or []   # 必须在 repath 之后取，才是同一条引用链
assert specs, "源 run 的 chart_specs 为空"

# ── 5. 把 CHART-01（产业链）换成 AI 生成图 ────────────────────────────
chain_spec = next(
    (s for s in specs if s.get("chart_type") == "industry_chain"), specs[0]
)
chain_spec["render_mode"] = "generated_image"
chain_spec["image_uri"] = f"/api/v1/runs/{TARGET_RID}/artifacts/{chain_name}"
chain_spec["image_mime_type"] = "image/jpeg"
chain_spec["title"] = "低空经济产业链结构"
chain_spec["subtitle"] = "低空经济价值传导与供需流向"
chain_spec["source_line"] = "数据来源：产业链生图模型生成；经系统审计引擎校验。"
chain_spec["generation_image_model"] = "openai/gpt-image-2"
chain_spec["generation_prompt_model"] = "deepseek-v4-flash"
chain_spec["chain_template"] = "horizontal_flow"
chain_spec["footnotes"] = ["本图为产业链生图模型生成的示意图，非等比结构示意"]
print(f"CHART-01 已改为 AI 生成图（{chain_spec['chart_id']}）")

# ── 6. 生成 chart_result.json（阶段4 硬依赖） ─────────────────────────
src_chart_result = json.loads((s_art / "chart_result.json").read_text(encoding="utf-8"))
src_chart_result["run_id"] = TARGET_RID
src_chart_result["source_report_id"] = json.loads(
    (t_art / "interpretation_report.json").read_text(encoding="utf-8")
).get("report_id", src_chart_result.get("source_report_id"))
src_chart_result["generated_at"] = datetime.now().isoformat()
src_chart_result["artifact_dir"] = str(t_art.resolve())

# 用改造后的 spec 覆盖 chart_result 里对应的那张（按 chart_id 对齐）
by_id = {s["chart_id"]: s for s in specs}
src_chart_result["charts"] = [
    by_id.get(c.get("chart_id"), c) for c in (src_chart_result.get("charts") or [])
]
# 源里若没有该 chart_id 的条目，补上
existing = {c.get("chart_id") for c in src_chart_result["charts"]}
for s in specs:
    if s["chart_id"] not in existing:
        src_chart_result["charts"].append(s)
src_chart_result = repath(src_chart_result)

(t_art / "chart_result.json").write_text(
    json.dumps(src_chart_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print("已生成 chart_result.json（阶段4 依赖）")

# ── 7. 更新 state.json ────────────────────────────────────────────────
state = json.loads((target / "state.json").read_text(encoding="utf-8"))
sr = state["stage_results"]

sr["data_interpret"]["status"] = "approved"      # 阶段2 产物是真跑的，只是补上审核通过
sr["chart_generate"]["status"] = "approved"      # 阶段3 预置完成
sr["chart_generate"]["data"] = chart_data
sr["chart_generate"]["evidence_sources"] = ["chart_generator_engine"]
sr["chart_generate"]["error"] = None
sr["chart_generate"]["artifacts"] = [
    {
        "artifact_id": "chart_result_json",
        "kind": "chart_result_json",
        "uri": str((t_art / "chart_result.json").resolve()),
        "checksum": None,
        "revision": 1,
    },
] + [
    {
        "artifact_id": f"{s['chart_id']}_svg",
        "kind": "chart_svg",
        "uri": str((t_charts / f"{s['chart_id']}.svg").resolve()),
        "checksum": None,
        "revision": 1,
    }
    for s in specs
    if (t_charts / f"{s['chart_id']}.svg").exists()
]

state["current_stage"] = "chapter_write"   # resume 会自动定位到第一个未完成阶段 = 阶段4
state["status"] = "pending"
state["updated_at"] = datetime.now().isoformat()

(target / "state.json").write_text(
    json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)

print()
print("=== 完成 ===")
print(f"run          : {TARGET_RID}")
print(f"阶段状态      : " + ", ".join(f"{k}={v['status']}" for k, v in sr.items()))
print(f"图表         : {len(specs)} 张（CHART-01 为 AI 生成产业链图）")
print(f"current_stage: {state['current_stage']}, status={state['status']}")
print(f"备份         : {backup.name}")
