<script setup lang="ts">
import { RouterLink, useRouter } from 'vue-router'

const router = useRouter()
function goToCreate(topic: string): void {
  void router.push({ path: '/create', query: { topic } })
}
</script>

<script lang="ts">
export default { name: 'LandingView' }
</script>

<template>
  <div class="landing-container">
    <!-- Hero Section -->
    <section class="hero">
      <div class="hero-left">
        <div class="hero-kicker">
          <span class="kicker-dot" />
          <span>INDUSTRY RESEARCH PLATFORM</span>
        </div>
        <h1 class="hero-title">
          把行业研究，<br />
          从资料搜集推进到可审核报告
        </h1>
        <p class="hero-sub">
          5 个专业智能体协同完成数据采集、分析解读、图表生成、章节写作与报告融合，
          每一步都保留证据、版本与人工审核入口。
        </p>
        <div class="hero-cta">
          <RouterLink to="/create" class="btn-cta" data-testid="btn-start-report">
            <span>开始制作研究报告</span>
            <span class="chev">›</span>
          </RouterLink>
          <RouterLink to="/runs" class="btn-secondary" data-testid="btn-view-history">
            <span>查看历史研报</span>
            <span class="chev">›</span>
          </RouterLink>
        </div>

        <div class="hero-topics">
          <span class="topic-label">热门研究范例：</span>
          <button
            v-for="t in ['商业航天', '低空经济', '固态电池', '光模块', '白酒行业']"
            :key="t"
            type="button"
            class="topic-chip interactive"
            :data-testid="`chip-${t}`"
            @click="goToCreate(t)"
          >
            {{ t }} ↗
          </button>
        </div>
      </div>

      <!-- 右侧插画卡片簇 (Open Design: Tonal Layering & Paper Outlines) -->
      <div class="hero-right" aria-hidden="true">
        <!-- 背景纸片叠层 -->
        <div class="paper p1" />
        <div class="paper p2" />
        <div class="paper p3" />

        <!-- 行业链结构卡 -->
        <div class="card-chain">
          <div class="chain-header">
            <span class="title">行业链结构</span>
            <span class="chain-sub">全景解构</span>
          </div>
          <div class="chain-bar" />
          <div class="chain-flow">
            <span class="chain-box">上游</span>
            <span class="chain-arr">→</span>
            <span class="chain-box">中游</span>
            <span class="chain-arr">→</span>
            <span class="chain-box">下游</span>
          </div>
          <div class="chain-row2">
            <span class="chain-box subtle">研发设计</span>
            <span class="chain-box subtle">原料采购</span>
            <span class="chain-box subtle">精深制造</span>
            <span class="chain-box subtle">终端分销</span>
          </div>
        </div>

        <!-- 趋势图表卡 -->
        <div class="card-chart">
          <div class="chart-header">
            <span class="title">行业趋势与预测</span>
            <span class="chart-badge">ECharts 矢量引擎</span>
          </div>
          <div class="legend">
            <span><i style="background: #1e3a5c" />市场规模(亿元)</span>
            <span><i style="background: #b7791f" />增长率(%)</span>
          </div>
          <svg viewBox="0 0 260 120" preserveAspectRatio="none" class="chart-svg">
            <defs>
              <linearGradient id="chartAreaGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="#1e3a5c" stop-opacity="0.16" />
                <stop offset="100%" stop-color="#1e3a5c" stop-opacity="0.01" />
              </linearGradient>
            </defs>

            <!-- 坐标网格 -->
            <line x1="28" y1="12" x2="28" y2="98" stroke="#E3DCCD" stroke-width="0.8" />
            <line x1="28" y1="98" x2="252" y2="98" stroke="#E3DCCD" stroke-width="0.8" />
            <line x1="28" y1="76" x2="252" y2="76" stroke="#EFE9DC" stroke-width="0.6" stroke-dasharray="3,3" />
            <line x1="28" y1="54" x2="252" y2="54" stroke="#EFE9DC" stroke-width="0.6" stroke-dasharray="3,3" />
            <line x1="28" y1="32" x2="252" y2="32" stroke="#EFE9DC" stroke-width="0.6" stroke-dasharray="3,3" />

            <!-- 面积填充 -->
            <polygon
              points="45,68 80,65 115,48 150,52 185,35 220,18 245,22 245,98 45,98"
              fill="url(#chartAreaGrad)"
            />

            <!-- Y 轴刻度文字 (清晰度调优) -->
            <text x="6" y="101" class="axis-num">0</text>
            <text x="3" y="79" class="axis-num">25</text>
            <text x="3" y="57" class="axis-num">50</text>
            <text x="3" y="35" class="axis-num">75</text>

            <!-- X 轴年份 -->
            <text x="38" y="112" class="axis-num">2016</text>
            <text x="73" y="112" class="axis-num">2018</text>
            <text x="108" y="112" class="axis-num">2020</text>
            <text x="143" y="112" class="axis-num">2022</text>
            <text x="178" y="112" class="axis-num">2024</text>
            <text x="218" y="112" class="axis-num">2025E</text>

            <!-- 蓝线：市场规模趋势 -->
            <polyline
              points="45,68 80,65 115,48 150,52 185,35 220,18 245,22"
              fill="none"
              stroke="#1E3A5C"
              stroke-width="1.8"
              stroke-linejoin="round"
            />
            <!-- 蓝线数据拐点圆点 -->
            <circle cx="45" cy="68" r="2.5" fill="#1E3A5C" stroke="#FFFFFF" stroke-width="1.2" />
            <circle cx="80" cy="65" r="2.5" fill="#1E3A5C" stroke="#FFFFFF" stroke-width="1.2" />
            <circle cx="115" cy="48" r="2.5" fill="#1E3A5C" stroke="#FFFFFF" stroke-width="1.2" />
            <circle cx="150" cy="52" r="2.5" fill="#1E3A5C" stroke="#FFFFFF" stroke-width="1.2" />
            <circle cx="185" cy="35" r="2.5" fill="#1E3A5C" stroke="#FFFFFF" stroke-width="1.2" />
            <circle cx="220" cy="18" r="2.5" fill="#1E3A5C" stroke="#FFFFFF" stroke-width="1.2" />
            <circle cx="245" cy="22" r="2.5" fill="#1E3A5C" stroke="#FFFFFF" stroke-width="1.2" />

            <!-- 金线：增长率折线 -->
            <polyline
              points="45,82 80,75 115,58 150,62 185,48 220,30 245,22"
              fill="none"
              stroke="#B7791F"
              stroke-width="1.8"
              stroke-linejoin="round"
            />
            <!-- 金线数据拐点圆点 -->
            <circle cx="45" cy="82" r="2.2" fill="#B7791F" stroke="#FFFFFF" stroke-width="1" />
            <circle cx="80" cy="75" r="2.2" fill="#B7791F" stroke="#FFFFFF" stroke-width="1" />
            <circle cx="115" cy="58" r="2.2" fill="#B7791F" stroke="#FFFFFF" stroke-width="1" />
            <circle cx="150" cy="62" r="2.2" fill="#B7791F" stroke="#FFFFFF" stroke-width="1" />
            <circle cx="185" cy="48" r="2.2" fill="#B7791F" stroke="#FFFFFF" stroke-width="1" />
            <circle cx="220" cy="30" r="2.2" fill="#B7791F" stroke="#FFFFFF" stroke-width="1" />
            <circle cx="245" cy="22" r="2.2" fill="#B7791F" stroke="#FFFFFF" stroke-width="1" />
          </svg>
        </div>

        <!-- 研报主封面卡 (Double-rule Masthead) -->
        <div class="card-main">
          <div class="gold-line" />
          <div class="r-title">行业研究报告</div>
          <div class="r-en">INDUSTRY RESEARCH REPORT</div>
          <div class="r-rules">
            <div class="rule-thick" />
            <div class="rule-thin" />
          </div>
          <table class="r-table">
            <tbody>
              <tr>
                <td class="lbl">执行系统</td>
                <td class="val">行业研究多智能体协同系统</td>
              </tr>
              <tr>
                <td class="lbl">研究范式</td>
                <td class="val">全链路五阶段 · 证据闭环</td>
              </tr>
              <tr>
                <td class="lbl">报告版本</td>
                <td class="val">Formal Release v1.0</td>
              </tr>
              <tr>
                <td class="lbl">审计穿透</td>
                <td class="val text-gold">100% 原始数据来源可追溯</td>
              </tr>
            </tbody>
          </table>
          <div class="watermark-char">研</div>
        </div>

        <!-- 审核通过浮标 -->
        <div class="badge-pass">
          <span class="pass-dot" />
          <span class="check">✓</span>
          <span class="pass-text">全流程审核通过</span>
        </div>

        <!-- 底部流程链条 -->
        <div class="flow-bar">
          <span class="flow-step">数据采集</span><span class="arrow">→</span>
          <span class="flow-step">数据解读</span><span class="arrow">→</span>
          <span class="flow-step">图表生成</span><span class="arrow">→</span>
          <span class="flow-step">章节撰写</span><span class="arrow">→</span>
          <span class="flow-step">报告融合</span>
        </div>
      </div>
    </section>

    <div class="divider-rule" />

    <!-- 核心特性区 -->
    <section class="features">
      <div class="features-grid">
        <div class="feature-item">
          <div class="feature-badge">
            <span class="badge-bullet" />
            <span>EVIDENCE-FIRST</span>
          </div>
          <div class="feature-title">证据可追溯</div>
          <div class="feature-desc">
            每项关键结论均精准关联数据来源、发布机构、时点与证据编号，从底层杜绝大模型幻觉。
          </div>
        </div>
        <div class="feature-item">
          <div class="feature-badge">
            <span class="badge-bullet" />
            <span>HUMAN-IN-THE-LOOP</span>
          </div>
          <div class="feature-title">人机协同审核</div>
          <div class="feature-desc">
            支持在五大阶段逐级审核把关，或开启一键自动放行，自由干预遴选图表与校准论点。
          </div>
        </div>
        <div class="feature-item">
          <div class="feature-badge">
            <span class="badge-bullet" />
            <span>MULTI-FORMAT</span>
          </div>
          <div class="feature-title">多格式交付</div>
          <div class="feature-desc">
            标准排版的一键交付系统，支持生成轻量 Markdown、高保真交互式 HTML 与离线归档 PDF。
          </div>
        </div>
      </div>
    </section>

    <div class="divider-rule" style="margin-top: 36px" />

    <!-- 五阶段流程序列 -->
    <section class="stages">
      <div class="stages-header">
        <div>
          <h2 class="stages-title">全链路五阶段协同体系</h2>
          <span class="stages-sub muted">从原始问财数据探查、主线逻辑推演直至高质量研报终稿归档</span>
        </div>
        <RouterLink to="/create" class="stages-quick-link">
          开始新研报 ›
        </RouterLink>
      </div>
      <div class="stages-grid">
        <div class="stage-item">
          <div class="stage-num">01</div>
          <div class="stage-label">数据采集</div>
          <div class="stage-desc muted">同花顺问财实时结构化数据清洗与量化指标初筛</div>
          <div class="stage-line" />
        </div>
        <div class="stage-item">
          <div class="stage-num">02</div>
          <div class="stage-label">数据解读</div>
          <div class="stage-desc muted">多维度财务分析、核心假设推演与主线逻辑提取</div>
          <div class="stage-line" />
        </div>
        <div class="stage-item">
          <div class="stage-num">03</div>
          <div class="stage-label">图表生成</div>
          <div class="stage-desc muted">ECharts 工业级矢量图表绘制与洞察标注生成</div>
          <div class="stage-line" />
        </div>
        <div class="stage-item">
          <div class="stage-num">04</div>
          <div class="stage-label">章节撰写</div>
          <div class="stage-desc muted">七大核心章节分布式起草、证据关联与交叉印证</div>
          <div class="stage-line" />
        </div>
        <div class="stage-item">
          <div class="stage-num">05</div>
          <div class="stage-label">报告融合</div>
          <div class="stage-desc muted">一致性审校门禁、多格式渲染与最终合规交付</div>
          <div class="stage-line" />
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
/* ── Open Design: Modern Academic Manuscript Tokens ── */
.landing-container {
  width: 100%;
  max-width: 1360px;
  margin: 0 auto;
  padding: 16px 16px 64px;
  color: #172638;
}

/* ── Hero ── */
.hero {
  padding: 28px 0 20px;
  display: grid;
  grid-template-columns: 1.05fr 0.95fr;
  gap: 24px;
  align-items: center;
}
.hero-left {
  padding-right: 28px;
}
.hero-kicker {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  letter-spacing: 2.5px;
  color: #b7791f;
  font-weight: 700;
  margin-bottom: 12px;
}
.kicker-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #b7791f;
}
.hero-title {
  font-family: Georgia, 'Times New Roman', 'Songti SC', 'STZhongsong', serif;
  font-size: 40px;
  font-weight: 700;
  line-height: 1.38;
  letter-spacing: -0.015em;
  color: #1e3a5c;
  margin: 0;
}
.hero-sub {
  font-size: 15.5px;
  line-height: 1.75;
  color: #4a5568;
  margin-top: 22px;
  max-width: 540px;
}
.hero-cta {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 32px;
  flex-wrap: wrap;
}
.btn-cta {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 46px;
  padding: 0 24px;
  border-radius: 6px;
  background: #20364f;
  color: #ffffff;
  text-decoration: none;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.5px;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  border: 1px solid rgba(255, 255, 255, 0.15);
  cursor: pointer;
  box-shadow: 0 3px 10px rgba(32, 54, 79, 0.22);
}
.btn-cta:hover {
  background: #142538;
  transform: translateY(-1.5px);
  box-shadow: 0 6px 16px rgba(32, 54, 79, 0.28);
}
.btn-cta .chev {
  font-size: 18px;
  line-height: 1;
  transition: transform 0.2s ease;
}
.btn-cta:hover .chev {
  transform: translateX(3px);
}

/* 次级幽灵按钮 (Ghost Button) */
.btn-secondary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 46px;
  padding: 0 20px;
  border-radius: 6px;
  background: #ffecfa;
  background: #fffffb;
  color: #20364f;
  text-decoration: none;
  font-size: 14.5px;
  font-weight: 600;
  border: 1px solid #d9d3c7;
  transition: all 0.2s ease;
  box-shadow: 0 1px 3px rgba(32, 54, 79, 0.04);
}
.btn-secondary:hover {
  background: #f7f3ea;
  border-color: #b0a89a;
  transform: translateY(-1px);
}
.btn-secondary .chev {
  font-size: 16px;
  color: #b7791f;
  transition: transform 0.2s ease;
}
.btn-secondary:hover .chev {
  transform: translateX(2px);
}

/* 热门范例胶囊 */
.hero-topics {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 20px;
  flex-wrap: wrap;
  font-size: 12px;
}
.topic-label {
  color: #8f8a7a;
}
.topic-chip {
  padding: 3px 10px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid #e3ddcd;
  color: #4a5568;
  font-size: 11.5px;
  font-family: inherit;
  line-height: 1.4;
  cursor: pointer;
  transition: all 0.15s ease;
}
.topic-chip:hover {
  border-color: #b7791f;
  color: #1e3a5c;
  background: #fff;
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.06);
}

/* ── 右侧插画卡片簇 ── */
.hero-right {
  position: relative;
  height: 470px;
  margin-top: 6px;
}

/* 背景纸片叠层 (Paper Edge) */
.paper {
  position: absolute;
  background: #f9f5ed;
  border: 1px solid #d9d3c7;
  border-radius: 4px;
  box-shadow: 0 3px 14px rgba(32, 54, 79, 0.05);
}
.paper.p1 {
  width: 290px;
  height: 180px;
  left: 15px;
  top: 75px;
  transform: rotate(-3.5deg);
}
.paper.p2 {
  width: 270px;
  height: 170px;
  right: 45px;
  top: 45px;
  transform: rotate(2deg);
  opacity: 0.75;
}
.paper.p3 {
  width: 250px;
  height: 200px;
  left: 95px;
  bottom: 25px;
  transform: rotate(-2deg);
  opacity: 0.5;
}

/* 行业链卡 */
.card-chain {
  position: absolute;
  right: 55px;
  top: 15px;
  width: 280px;
  background: #fdfaf3;
  border: 1px solid #d9d3c7;
  border-radius: 5px;
  transform: rotate(1deg);
  box-shadow: 0 4px 14px rgba(32, 54, 79, 0.06);
  padding: 12px 14px;
  z-index: 2;
}
.chain-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 5px;
}
.card-chain .title {
  font-family: Georgia, 'Songti SC', serif;
  font-size: 14.5px;
  font-weight: 700;
  color: #1e3a5c;
}
.chain-sub {
  font-size: 10px;
  color: #b7791f;
  font-weight: 600;
}
.card-chain .chain-bar {
  height: 1px;
  background: #e3ddcd;
  margin-bottom: 8px;
}
.chain-flow {
  display: flex;
  align-items: center;
}
.chain-box {
  padding: 3px 8px;
  border: 1px solid #d9d3c7;
  border-radius: 3px;
  font-size: 11px;
  color: #1e3a5c;
  font-weight: 600;
  background: #ffffff;
}
.chain-box.subtle {
  font-weight: 400;
  font-size: 10px;
  color: #4a5568;
  padding: 2px 6px;
}
.chain-arr {
  color: #b7791f;
  font-size: 11px;
  margin: 0 4px;
  font-weight: 700;
}
.chain-row2 {
  display: flex;
  gap: 5px;
  margin-top: 6px;
}

/* 趋势图表卡 */
.card-chart {
  position: absolute;
  left: 5px;
  top: 115px;
  width: 265px;
  background: #ffffff;
  border: 1px solid #d9d3c7;
  border-radius: 5px;
  transform: rotate(-4.5deg);
  box-shadow: 0 5px 20px rgba(32, 54, 79, 0.09);
  padding: 12px 14px;
  z-index: 3;
}
.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}
.card-chart .title {
  font-family: Georgia, 'Songti SC', serif;
  font-size: 13.5px;
  font-weight: 700;
  color: #1e3a5c;
}
.chart-badge {
  font-size: 9px;
  padding: 1px 5px;
  background: #eff6ff;
  color: #1d4ed8;
  border-radius: 2px;
  border: 1px solid #bfdbfe;
}
.card-chart .legend {
  display: flex;
  gap: 12px;
  font-size: 10px;
  color: #667487;
  margin-bottom: 6px;
}
.card-chart .legend span {
  display: flex;
  align-items: center;
  gap: 4px;
}
.card-chart .legend i {
  width: 10px;
  height: 2px;
  border-radius: 1px;
  display: inline-block;
}
.chart-svg {
  width: 100%;
  height: 105px;
  overflow: visible;
}
.axis-num {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 9.5px;
  fill: #8f8a7a;
  font-variant-numeric: tabular-nums;
}

/* 研报主卡 */
.card-main {
  position: absolute;
  right: -5px;
  top: 100px;
  width: 330px;
  background: #fdfaf3;
  border: 1px solid #d9d3c7;
  border-radius: 5px;
  transform: rotate(1.5deg);
  box-shadow: 0 6px 24px rgba(32, 54, 79, 0.12);
  padding: 18px 22px;
  z-index: 4;
  overflow: hidden;
}
.card-main .gold-line {
  width: 160px;
  height: 2.5px;
  background: #b7791f;
  margin: 0 auto 10px;
}
.card-main .r-title {
  font-family: Georgia, 'Songti SC', serif;
  font-size: 26px;
  font-weight: 700;
  color: #1b3a5f;
  line-height: 1.2;
}
.card-main .r-en {
  font-size: 10px;
  letter-spacing: 2px;
  color: #4a5568;
  margin-top: 2px;
}
.card-main .r-rules {
  margin: 8px 0 10px;
}
.rule-thick {
  height: 2px;
  background: #1b3a5f;
  width: 100%;
}
.rule-thin {
  height: 1px;
  background: #1b3a5f;
  width: 100%;
  margin-top: 2.5px;
}
.r-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
  line-height: 1.4;
}
.r-table td {
  padding: 4px 0;
  border-bottom: 1px solid #eae3d5;
  color: #172638;
}
.r-table .lbl {
  color: #8f8a7a;
  width: 75px;
}
.r-table .val {
  color: #1b3a5f;
  font-weight: 600;
  border-left: 1px solid #eae3d5;
  padding-left: 10px;
}
.r-table .text-gold {
  color: #b7791f;
}
.watermark-char {
  position: absolute;
  right: 12px;
  bottom: -16px;
  font-family: Georgia, 'Songti SC', serif;
  font-size: 96px;
  font-weight: 700;
  color: #1b3a5f;
  opacity: 0.06;
  line-height: 1;
  pointer-events: none;
}

/* 审核通过浮标 */
.badge-pass {
  position: absolute;
  left: 90px;
  top: 70px;
  z-index: 6;
  background: #ffffff;
  border: 1px solid #d9d3c7;
  border-radius: 4px;
  padding: 6px 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  box-shadow: 0 4px 14px rgba(32, 54, 79, 0.1);
  transform: rotate(-3deg);
  font-size: 13px;
  font-weight: 600;
  color: #1e3a5c;
}
.pass-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
  animation: pass-pulse 2s infinite;
}
@keyframes pass-pulse {
  0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
  70% { transform: scale(1); box-shadow: 0 0 0 5px rgba(16, 185, 129, 0); }
  100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
}
.badge-pass .check {
  color: #10b981;
  font-size: 14px;
  font-weight: 700;
}

/* 底部流程条 */
.flow-bar {
  position: absolute;
  left: 15px;
  right: -5px;
  bottom: 22px;
  height: 40px;
  background: #f4efe6;
  border: 1px solid #d9d3c7;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 16px;
  z-index: 5;
  box-shadow: 0 2px 8px rgba(32, 54, 79, 0.04);
}
.flow-step {
  font-size: 12.5px;
  color: #1e3a5c;
  font-weight: 600;
  white-space: nowrap;
}
.flow-bar .arrow {
  color: #b7791f;
  margin: 0 8px;
  font-size: 12px;
  font-weight: 700;
}

/* 分隔线 */
.divider-rule {
  height: 1px;
  background: #d9d3c7;
  width: 100%;
  margin: 28px 0 32px;
}

/* ── 核心特性区 ── */
.features-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
}
.feature-item {
  padding: 18px 22px;
  background: #fffefb;
  border: 1px solid #d9d3c7;
  border-radius: 6px;
  transition: transform 0.2s, box-shadow 0.2s, border-color 0.2s;
  box-shadow: 0 2px 8px rgba(32, 54, 79, 0.03);
}
.feature-item:hover {
  transform: translateY(-2px);
  border-color: #bfa472;
  box-shadow: 0 6px 18px rgba(32, 54, 79, 0.07);
}
.feature-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 10.5px;
  letter-spacing: 1.5px;
  color: #b7791f;
  font-weight: 700;
  margin-bottom: 8px;
}
.badge-bullet {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #b7791f;
}
.feature-title {
  font-family: Georgia, 'Songti SC', serif;
  font-size: 18px;
  font-weight: 700;
  color: #1e3a5c;
  margin-bottom: 8px;
}
.feature-desc {
  font-size: 13.5px;
  color: #4a5568;
  line-height: 1.65;
}

/* ── 五阶段流水线 ── */
.stages {
  padding: 6px 0 16px;
}
.stages-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 22px;
}
.stages-title {
  font-family: Georgia, 'Songti SC', serif;
  font-size: 21px;
  font-weight: 700;
  color: #1e3a5c;
  margin: 0 0 4px;
}
.stages-sub {
  font-size: 12.5px;
  color: #8f8a7a;
}
.stages-quick-link {
  font-size: 13px;
  color: #1e3a5c;
  font-weight: 600;
  text-decoration: none;
}
.stages-quick-link:hover {
  color: #b7791f;
}
.stages-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
}
.stage-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  position: relative;
  padding: 12px 14px;
  background: #fffefb;
  border: 1px solid #e3ddcd;
  border-radius: 5px;
  transition: all 0.2s ease;
}
.stage-item:hover {
  border-color: #bfa472;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(32, 54, 79, 0.05);
}
.stage-num {
  font-family: Georgia, 'Songti SC', serif;
  font-size: 28px;
  font-weight: 700;
  color: #b7791f;
  line-height: 1;
  margin-bottom: 6px;
}
.stage-label {
  font-size: 15px;
  font-weight: 700;
  color: #1e3a5c;
  margin-bottom: 4px;
}
.stage-desc {
  font-size: 11.5px;
  line-height: 1.5;
  color: #667487;
}
.stage-line {
  height: 2px;
  width: 100%;
  margin-top: 10px;
  background: repeating-linear-gradient(to right, #b7791f 0 3px, transparent 3px 6px);
  opacity: 0.6;
}
.stage-item:last-child .stage-line {
  display: none;
}

/* 响应式适配 */
@media (max-width: 1080px) {
  .hero {
    grid-template-columns: 1fr;
    gap: 36px;
  }
  .hero-left {
    padding-right: 0;
  }
  .hero-right {
    height: 420px;
    max-width: 480px;
    margin: 0 auto;
  }
  .features-grid {
    grid-template-columns: 1fr;
  }
  .stages-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
@media (max-width: 640px) {
  .hero-title {
    font-size: 30px;
  }
  .hero-right {
    display: none;
  }
  .stages-grid {
    grid-template-columns: 1fr;
  }
}
</style>
