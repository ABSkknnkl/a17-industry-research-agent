/** 五份行业研究报告索引 — 数据由 meta.json 提供，缺失时使用内置列表 */
const FALLBACK = [
  {
    pack_id: "solid-battery",
    title_pack: "固态电池产业化研究",
    headline: "固态电池处于中试向小批量过渡期，电解质路线与设备投资是验证重点。",
    total_score: null,
    delivery_status: "ready_with_limits",
  },
  {
    pack_id: "humanoid-robot",
    title_pack: "人形机器人产业链研究",
    headline: "工厂试点与核心件国产化双推进，丝杠/减速器/六维力是卡点。",
    total_score: null,
    delivery_status: "ready_with_limits",
  },
  {
    pack_id: "satcom-leo",
    title_pack: "卫星互联网低轨星座研究",
    headline: "密集发射与终端降本并行，制造成本与频轨资源是关键约束。",
    total_score: null,
    delivery_status: "ready_with_limits",
  },
  {
    pack_id: "hydrogen-truck",
    title_pack: "氢能重卡与燃料电池研究",
    headline: "示范城市群纵深运营，氢价与加氢站密度决定拐点。",
    total_score: null,
    delivery_status: "ready_with_limits",
  },
  {
    pack_id: "evtol-low-altitude",
    title_pack: "低空经济 eVTOL 产业研究",
    headline: "适航与场景试点叠加期，运营披露与零部件定点可跟踪。",
    total_score: null,
    delivery_status: "ready_with_limits",
  },
];

const pathOf = (id) => `report-packs/${id}/index.html`;

async function loadMeta() {
  try {
    const res = await fetch("report-packs/meta.json", { cache: "no-store" });
    if (!res.ok) throw new Error("no meta");
    const arr = await res.json();
    return arr.map((r) => ({
      pack_id: r.pack_id,
      title_pack: r.title_pack || r.topic,
      headline: r.headline || r.title || "",
      total_score: r.total_score,
      delivery_status: r.delivery_status,
      status: r.status,
      topic: r.topic,
    }));
  } catch {
    return FALLBACK;
  }
}

function render(list) {
  const listEl = document.getElementById("list");
  const titleEl = document.getElementById("stage-title");
  const openEl = document.getElementById("open-tab");
  const frame = document.getElementById("frame");
  const meta = document.getElementById("meta");
  meta.innerHTML = `共 <b>${list.length}</b> 份 · Agent5 融合产物<br/>路径：<code>report-packs/</code>`;

  listEl.innerHTML = "";
  list.forEach((item, idx) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "card" + (idx === 0 ? " active" : "");
    btn.dataset.id = item.pack_id;
    const score =
      item.total_score != null ? `${item.total_score} 分` : "—";
    btn.innerHTML = `
      <h3>${item.title_pack}</h3>
      <p>${item.headline || ""}</p>
      <div class="tags">
        <span class="tag score">质量 ${score}</span>
        <span class="tag ${item.delivery_status === "ready" ? "ok" : ""}">${item.delivery_status || item.status || ""}</span>
        <span class="tag">${item.pack_id}</span>
      </div>`;
    btn.addEventListener("click", () => select(item, list));
    listEl.appendChild(btn);
  });

  if (list[0]) select(list[0], list);
}

function select(item, list) {
  document.querySelectorAll(".card").forEach((el) => {
    el.classList.toggle("active", el.dataset.id === item.pack_id);
  });
  const url = pathOf(item.pack_id);
  document.getElementById("stage-title").textContent = item.title_pack;
  const openEl = document.getElementById("open-tab");
  openEl.href = url;
  document.getElementById("frame").src = url;
  void list;
}

loadMeta().then(render);
