/*
 * 报告 HTML 样式 —— 从真实后端产物捕获，非手写。
 *
 * 来源：backend/output/report-preview.html 的 <style> 块（由 render_html 渲染），
 * 样式来自 backend/app/reporting/templates/report-style.css.j2 + report.html.j2。
 *
 * 直接复用真实样式，保证 mock 的报告预览与真实交付件视觉一致；
 * 后端模板改版时需要重新捕获（本文件无逻辑，纯样式常量）。
 */
export const REPORT_HTML_CSS = `

:root {
  color-scheme: light;
  --ink: #15191e;
  --text: #292e34;
  --muted: #626a73;
  --rule: #242a31;
  --hairline: #b9bec4;
  --soft-line: #dfe2e5;
  --paper: #ffffff;
  --canvas: #eef0f2;
  --soft-surface: #f4f5f6;
  --positive-surface: #edf6f0;
  --negative-surface: #fbefef;
  --warning-surface: #faf4e8;
  --accent: #173653;
  --positive: #1f6940;
  --negative: #9a3434;
  --warning: #865d16;
}

* {
  box-sizing: border-box;
}

html,
body {
  margin: 0;
  background: var(--canvas);
}

html {
  scroll-behavior: smooth;
  scroll-padding-top: 16mm;
}

body {
  color: var(--text);
  font-family: "Songti SC", "STSong", "SimSun", "Noto Serif CJK SC", serif;
  font-size: 10.5pt;
  line-height: 1.62;
  font-variant-numeric: tabular-nums lining-nums;
  text-rendering: optimizeLegibility;
}

.document-shell {
  width: 210mm;
  min-height: 297mm;
  margin: 0 auto;
  padding: 14mm 13mm 13mm;
  background: var(--paper);
  box-shadow: 0 5mm 14mm rgb(24 31 38 / 0.09);
}

.report-header {
  padding-bottom: 4mm;
  border-bottom: 1.4pt solid var(--rule);
}

.identity-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 16mm;
  padding-bottom: 4mm;
  border-bottom: 0.5pt solid var(--hairline);
}

.company-identity {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 3.5mm;
}

.company-mark {
  display: flex;
  width: 14mm;
  height: 14mm;
  flex: 0 0 14mm;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  color: var(--accent);
  background: var(--paper);
  border: 0.7pt solid var(--rule);
  font-family: "Heiti SC", "STHeiti", "Microsoft YaHei", sans-serif;
  font-size: 10pt;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.company-mark.has-logo {
  padding: 1.6mm;
  background: var(--paper);
}

.company-mark img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.company-name {
  overflow: hidden;
}

.company-name strong {
  display: block;
  overflow: hidden;
  color: var(--ink);
  font-family: "Heiti SC", "STHeiti", "Microsoft YaHei", sans-serif;
  font-size: 14pt;
  font-weight: 650;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.company-name span {
  display: block;
  margin-top: 0.8mm;
  color: var(--muted);
  font-family: "Times New Roman", "Songti SC", serif;
  font-size: 8.2pt;
  letter-spacing: 0.035em;
}

.document-class {
  flex: 0 0 auto;
  padding: 1mm 0 1mm 5mm;
  text-align: right;
  border-left: 0.5pt solid var(--hairline);
}

.document-class strong {
  display: block;
  color: var(--ink);
  font-family: "Heiti SC", "STHeiti", "Microsoft YaHei", sans-serif;
  font-size: 10.5pt;
  font-weight: 650;
}

.title-block {
  padding: 8mm 0 6mm;
  text-align: left;
}

h1,
h2,
h3,
p {
  margin-top: 0;
}

h1 {
  max-width: 172mm;
  margin: 0 0 4mm;
  color: var(--ink);
  font-family: "Songti SC", "STSong", "SimSun", serif;
  font-size: 25pt;
  font-weight: 700;
  line-height: 1.24;
  letter-spacing: 0.015em;
}

.report-deck {
  max-width: 174mm;
  margin: 0;
  padding-left: 5mm;
  color: var(--ink);
  border-left: 2.2pt solid var(--accent);
  font-size: 12.5pt;
  font-weight: 650;
  line-height: 1.58;
  letter-spacing: 0.008em;
}

.report-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 1.2mm 0;
  margin: 0;
  padding: 2.7mm 0;
  color: var(--muted);
  border-top: 0.5pt solid var(--hairline);
  border-bottom: 0.5pt solid var(--hairline);
  font-family: "Heiti SC", "STHeiti", "Microsoft YaHei", sans-serif;
  font-size: 8.2pt;
  line-height: 1.4;
}

.report-meta span + span::before {
  content: "·";
  margin: 0 2.2mm;
  color: var(--hairline);
}

.front-matter {
  padding-top: 2mm;
}

.report-navigation {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  min-height: 11mm;
  align-items: stretch;
  gap: 4mm;
  margin: 0 -13mm;
  padding: 0 13mm;
  overflow: hidden;
  background: rgb(255 255 255 / 0.96);
  border-bottom: 0.5pt solid var(--soft-line);
  box-shadow: 0 1.2mm 3mm rgb(24 31 38 / 0.04);
  backdrop-filter: blur(6px);
  font-family: "Heiti SC", "STHeiti", "Microsoft YaHei", sans-serif;
  font-size: 8.2pt;
}

.report-navigation-label {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  color: var(--ink);
  font-weight: 700;
}

.report-navigation ol {
  display: flex;
  min-width: 0;
  margin: 0;
  padding: 0;
  gap: 4.5mm;
  overflow-x: auto;
  list-style: none;
  scrollbar-width: thin;
}

.report-navigation li {
  flex: 0 0 auto;
  margin: 0;
}

.report-navigation a {
  position: relative;
  display: flex;
  min-height: 11mm;
  align-items: center;
  color: var(--muted);
  text-decoration: none;
  transition: color 140ms ease, box-shadow 140ms ease;
}

.report-navigation a:hover,
.report-navigation a:focus-visible,
.report-navigation a[aria-current="true"] {
  color: var(--accent);
  box-shadow: inset 0 -1.5pt 0 var(--accent);
}

.report-columns {
  display: block;
}

.section-pair {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: start;
  gap: 0 10mm;
  break-inside: avoid;
}

.report-appendix {
  padding-top: 1mm;
}

.report-section {
  margin-top: 8mm;
  break-inside: auto;
  orphans: 3;
  widows: 3;
}

.section-pair .report-section {
  min-width: 0;
}

.report-section h2 {
  margin: 0 0 3.2mm;
  padding-bottom: 1.8mm;
  color: var(--ink);
  border-bottom: 0.8pt solid var(--rule);
  font-family: "Heiti SC", "STHeiti", "Microsoft YaHei", sans-serif;
  font-size: 13pt;
  font-weight: 700;
  line-height: 1.35;
  break-after: avoid;
  scroll-margin-top: 16mm;
}

.report-lead-section h2 {
  margin-bottom: 4.5mm;
  padding-bottom: 0;
  border-bottom: 0;
}

.section-lead {
  margin-bottom: 3mm;
  padding: 2.6mm 3.2mm;
  color: var(--ink);
  background: var(--soft-surface);
  border-left: 2pt solid var(--hairline);
  font-weight: 650;
  line-height: 1.62;
  text-align: justify;
  text-justify: inter-ideograph;
}

.report-section > p {
  margin-bottom: 2.4mm;
  text-align: justify;
  text-indent: 2em;
  text-justify: inter-ideograph;
}

.report-section ul {
  margin: 2mm 0 0;
  padding-left: 5mm;
}

.report-section li {
  margin: 1.2mm 0;
  text-align: justify;
  text-justify: inter-ideograph;
}

.thesis-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.thesis-list li {
  display: grid;
  grid-template-columns: 8mm 1fr;
  gap: 3mm;
  margin: 0 0 2.4mm;
  padding: 3mm 3.4mm;
  background: var(--soft-surface);
  border-left: 2pt solid var(--soft-line);
  text-align: left;
}

.thesis-list li.tone-positive {
  border-left-color: var(--positive);
}

.thesis-list li.tone-negative {
  border-left-color: var(--negative);
}

.thesis-list li.tone-warning {
  border-left-color: var(--warning);
}

.thesis-list li.tone-positive .thesis-number,
.thesis-list li.tone-positive .thesis-copy strong {
  color: var(--positive);
}

.thesis-list li.tone-negative .thesis-number,
.thesis-list li.tone-negative .thesis-copy strong {
  color: var(--negative);
}

.thesis-list li.tone-warning .thesis-number,
.thesis-list li.tone-warning .thesis-copy strong {
  color: var(--warning);
}

.thesis-number {
  color: var(--accent);
  font-family: "Times New Roman", serif;
  font-size: 10.5pt;
  font-weight: 700;
  line-height: 1.45;
}

.thesis-copy strong {
  display: block;
  color: var(--ink);
  font-family: "Heiti SC", "STHeiti", "Microsoft YaHei", sans-serif;
  font-size: 10.5pt;
  line-height: 1.45;
}

.thesis-copy p {
  margin: 0.8mm 0 0;
  color: var(--text);
  line-height: 1.62;
  text-align: justify;
  text-justify: inter-ideograph;
}

.table-figure {
  margin: 4mm 0;
  overflow-x: auto;
  break-inside: auto;
}

.chart-figure {
  margin: 4mm 0;
  break-inside: avoid;
}

table {
  width: 100%;
  border-collapse: collapse;
  border-top: 1.2pt solid var(--rule);
  border-bottom: 1.2pt solid var(--rule);
  font-family: "Songti SC", "STSong", "SimSun", serif;
  font-size: 8.2pt;
  line-height: 1.4;
}

.data-table {
  table-layout: fixed;
}

.data-table th:first-child,
.data-table td:first-child {
  width: 28%;
  text-align: left;
}

caption {
  padding: 0 0 2mm;
  color: var(--ink);
  font-family: "Songti SC", "STSong", "SimSun", serif;
  font-size: 9.2pt;
  font-weight: 650;
  text-align: left;
  break-after: avoid;
}

th,
td {
  padding: 1.8mm 1.4mm;
  vertical-align: top;
  border: 0;
}

thead {
  background: var(--soft-surface);
  border-bottom: 0.7pt solid var(--rule);
  display: table-header-group;
}

th {
  color: var(--ink);
  font-family: "Heiti SC", "STHeiti", "Microsoft YaHei", sans-serif;
  font-size: 7.8pt;
  font-weight: 650;
  text-align: left;
}

tbody tr {
  transition: background-color 120ms ease;
}

tbody tr:hover {
  background: #f7f8f9;
}

.metric-table {
  table-layout: fixed;
}

.metric-table th:nth-child(1),
.metric-table td:nth-child(1) {
  width: 16%;
}

.metric-table th:nth-child(2),
.metric-table td:nth-child(2) {
  width: 17%;
  text-align: right;
}

.metric-table th:nth-child(3),
.metric-table td:nth-child(3) {
  width: 20%;
  text-align: right;
}

.metric-table td:nth-child(3) {
  color: var(--muted);
}

.metric-table th:nth-child(4),
.metric-table td:nth-child(4) {
  width: 13%;
  text-align: right;
}

.metric-table th:nth-child(5),
.metric-table td:nth-child(5) {
  width: 34%;
}

.data-table th:not(:first-child),
.data-table td:not(:first-child) {
  text-align: right;
}

.data-table tbody tr + tr {
  border-top: 0.35pt solid var(--soft-line);
}

.source-table {
  table-layout: fixed;
  font-size: 6.9pt;
}

.source-table tbody tr + tr {
  border-top: 0.35pt solid var(--soft-line);
}

.source-table th:nth-child(1),
.source-table td:nth-child(1) {
  width: 4%;
  text-align: center;
}

.source-table th:nth-child(2),
.source-table td:nth-child(2) {
  width: 25%;
}

.source-table th:nth-child(3),
.source-table td:nth-child(3) {
  width: 11%;
}

.source-table th:nth-child(4),
.source-table td:nth-child(4) {
  width: 10%;
}

.source-table th:nth-child(5),
.source-table td:nth-child(5) {
  width: 11%;
}

.source-table th:nth-child(6),
.source-table td:nth-child(6) {
  width: 21%;
}

.source-table th:nth-child(7),
.source-table td:nth-child(7) {
  width: 18%;
}

.source-table a {
  color: inherit;
  text-decoration: underline;
  text-decoration-thickness: 0.4pt;
  text-underline-offset: 1pt;
}

.source-method,
.source-level {
  display: block;
}

.source-method {
  color: var(--ink);
  font-weight: 650;
}

.source-level {
  margin-top: 0.5mm;
  color: var(--muted);
  font-size: 6.3pt;
}

.metric-value {
  color: var(--ink);
  font-weight: 750;
}

.tone-positive {
  color: var(--positive);
  font-weight: 700;
}

.tone-negative {
  color: var(--negative);
  font-weight: 700;
}

.tone-warning {
  color: var(--warning);
  font-weight: 700;
}

.tone-neutral {
  color: var(--text);
}

.metric-table td.tone-positive,
.data-table td.tone-positive {
  background: var(--positive-surface);
  box-shadow: inset 1.5pt 0 0 var(--positive);
}

.metric-table td.tone-negative,
.data-table td.tone-negative {
  background: var(--negative-surface);
  box-shadow: inset 1.5pt 0 0 var(--negative);
}

.metric-table td.tone-warning,
.data-table td.tone-warning {
  background: var(--warning-surface);
  box-shadow: inset 1.5pt 0 0 var(--warning);
}

.inline-number {
  color: var(--ink);
  font-weight: 750;
  white-space: nowrap;
}

.thesis-copy strong.inline-number,
.risk-copy strong.inline-number {
  display: inline;
  color: var(--ink);
  font-family: inherit;
  font-size: inherit;
  line-height: inherit;
}

.source-ref {
  margin-left: 0.6mm;
  color: var(--accent);
  font-family: "Times New Roman", serif;
  font-size: 6.5pt;
  font-weight: 700;
  text-decoration: none;
  vertical-align: super;
}

.table-notes,
.figure-notes,
.source-note {
  margin-top: 1.4mm;
  color: var(--muted);
  font-size: 7.2pt;
  line-height: 1.45;
  text-align: justify;
  text-justify: inter-ideograph;
}

.chart-figure svg {
  display: block;
  width: 100%;
  height: auto;
  overflow: visible;
}

figcaption {
  margin-top: 1.8mm;
  color: var(--ink);
  font-size: 9pt;
  font-weight: 650;
  text-align: center;
}

.risk-level.severity-high,
.risk-level.severity-medium,
.risk-level.severity-low {
  font-weight: 700;
}

.risk-level.severity-high {
  color: var(--negative);
}

.risk-level.severity-medium {
  color: var(--warning);
}

.risk-level.severity-low {
  color: var(--positive);
}

.risk-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.risk-list li {
  display: grid;
  grid-template-columns: 18mm 1fr;
  gap: 4mm;
  margin: 0 0 4mm;
  padding: 2.8mm 3.2mm;
  background: var(--soft-surface);
  border-left: 2pt solid var(--hairline);
  break-inside: avoid;
  text-align: left;
}

.risk-list li.severity-high,
.risk-list li:has(.severity-high) {
  background: var(--negative-surface);
  border-left-color: var(--negative);
}

.risk-list li.severity-medium,
.risk-list li:has(.severity-medium) {
  background: var(--warning-surface);
  border-left-color: var(--warning);
}

.risk-list li.severity-low,
.risk-list li:has(.severity-low) {
  background: var(--positive-surface);
  border-left-color: var(--positive);
}

.risk-list li.severity-high .inline-number,
.risk-list li:has(.severity-high) .inline-number {
  color: var(--negative);
}

.risk-level {
  padding-top: 0.35mm;
  font-family: "Heiti SC", "STHeiti", "Microsoft YaHei", sans-serif;
  font-size: 8.3pt;
  font-weight: 700;
  line-height: 1.45;
}

.risk-copy strong {
  display: block;
  color: var(--ink);
  font-family: "Heiti SC", "STHeiti", "Microsoft YaHei", sans-serif;
  font-size: 10.2pt;
  line-height: 1.45;
}

.risk-copy p {
  margin: 0.8mm 0 0;
  line-height: 1.62;
  text-align: justify;
  text-justify: inter-ideograph;
}

.data-gaps {
  padding: 3mm 3.5mm;
  background: var(--soft-surface);
  border-left: 2pt solid var(--hairline);
}

.data-gaps ul {
  margin-top: 0;
  columns: 1;
}

.data-gaps.is-balanced ul {
  columns: 2;
  column-gap: 10mm;
}

.data-gaps li {
  break-inside: avoid;
}

.report-appendix-section {
  margin-top: 10mm;
}

.source-intro {
  margin: 0 0 3mm;
  color: var(--muted);
  font-size: 8.2pt;
  line-height: 1.6;
  text-align: left;
  text-indent: 0 !important;
}

.source-details {
  border-bottom: 0.5pt solid var(--soft-line);
}

.source-details summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 0 2mm;
  color: var(--ink);
  cursor: pointer;
  list-style: none;
}

.source-details summary::-webkit-details-marker {
  display: none;
}

.source-details summary::after,
.source-details[open] summary::after {
  content: none;
}

.source-table-heading {
  font-family: "Songti SC", "STSong", "SimSun", serif;
  font-size: 9.2pt;
  font-weight: 650;
}

.source-toggle-button {
  flex: 0 0 auto;
  margin-left: 4mm;
  padding: 0.8mm 1.7mm;
  color: var(--accent);
  background: var(--soft-surface);
  border: 0.45pt solid var(--soft-line);
  border-radius: 2mm;
  font-family: "Heiti SC", "STHeiti", "Microsoft YaHei", sans-serif;
  font-size: 7pt;
  font-weight: 650;
  line-height: 1.3;
}

.source-details summary:hover .source-toggle-button,
.source-details summary:focus-visible .source-toggle-button {
  background: #e9edf1;
}

.source-details-content {
  margin: 0;
  padding-bottom: 1mm;
}

.visually-hidden {
  position: absolute !important;
  width: 1px !important;
  height: 1px !important;
  padding: 0 !important;
  overflow: hidden !important;
  clip: rect(0, 0, 0, 0) !important;
  white-space: nowrap !important;
  border: 0 !important;
}

a:focus-visible,
summary:focus-visible {
  outline: 1.5pt solid var(--accent);
  outline-offset: 1.5pt;
}

.report-footer {
  margin-top: 7mm;
  padding-top: 3mm;
  color: var(--muted);
  border-top: 0.6pt solid var(--rule);
  font-size: 6.8pt;
  line-height: 1.45;
}

.report-footer p {
  margin: 0 0 1mm;
}

.footer-mark {
  font-family: "Times New Roman", "Songti SC", serif;
  letter-spacing: 0.025em;
}

/* 9.8.3 institutional research layout */
.report-header {
  padding-bottom: 0;
  border-bottom: 1.5pt solid var(--accent);
}

.identity-row {
  min-height: 0;
  align-items: flex-start;
  padding: 0 0 4mm;
  border-bottom: 1.5pt solid var(--accent);
}

.company-identity {
  align-items: flex-start;
  gap: 2.5mm;
}

.company-mark {
  width: 11mm;
  height: 11mm;
  flex-basis: 11mm;
}

.company-name strong {
  color: var(--accent);
  font-size: 15pt;
  font-weight: 700;
}

.company-name span {
  margin-top: 1.2mm;
  color: #39495c;
  font-family: "Heiti SC", "STHeiti", "Microsoft YaHei", sans-serif;
  font-size: 8.4pt;
  letter-spacing: 0.015em;
}

.document-class {
  padding: 0;
  border-left: 0;
}

.document-class strong {
  color: var(--accent);
  font-size: 11pt;
  font-weight: 700;
}

.document-class span {
  display: block;
  margin-top: 1.2mm;
  color: #39495c;
  font-family: "Times New Roman", serif;
  font-size: 8.2pt;
}

.title-block {
  padding: 6mm 0 5mm;
}

.title-block.has-market-snapshot {
  display: grid;
  grid-template-columns: minmax(0, 2.18fr) minmax(52mm, 1fr);
  align-items: stretch;
  gap: 5.5mm;
}

.title-copy {
  min-width: 0;
}

h1 {
  max-width: none;
  margin-bottom: 3.2mm;
  color: #101820;
  font-size: 24pt;
  line-height: 1.28;
}

.report-deck {
  max-width: none;
  margin: 0;
  padding: 0;
  color: #28323d;
  border-left: 0;
  font-size: 10.4pt;
  font-weight: 400;
  line-height: 1.72;
  text-align: justify;
  text-justify: inter-ideograph;
}

.market-snapshot {
  min-width: 0;
  padding-left: 5.5mm;
  border-left: 0.5pt solid var(--hairline);
}

.market-snapshot h2 {
  margin: 0 0 2.5mm;
  color: var(--accent);
  font-family: "Heiti SC", "STHeiti", "Microsoft YaHei", sans-serif;
  font-size: 10.5pt;
  line-height: 1.3;
}

.market-snapshot dl {
  margin: 0;
}

.market-snapshot dl > div {
  display: grid;
  grid-template-columns: 25mm minmax(0, 1fr);
  gap: 2mm;
  padding: 1.35mm 0;
  border-bottom: 0.35pt solid var(--soft-line);
  font-size: 8.2pt;
  line-height: 1.35;
}

.market-snapshot dt {
  color: var(--muted);
}

.market-snapshot dd {
  margin: 0;
  color: var(--ink);
  font-weight: 650;
  text-align: right;
}

.market-snapshot p {
  margin: 2mm 0 0;
  color: var(--muted);
  font-size: 6.8pt;
  line-height: 1.45;
}

.report-meta {
  padding: 2.4mm 0;
  border-top: 0.5pt solid var(--hairline);
  border-bottom: 0;
  font-size: 7.5pt;
}

.report-meta span + span::before {
  content: "|";
  margin: 0 2.4mm;
  color: var(--hairline);
}

.report-section {
  margin-top: 6.5mm;
}

.report-analysis-section h2,
.report-risk-section h2 {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

.report-lead-section h2 {
  margin-bottom: 1.5mm;
  padding-bottom: 1.8mm;
  border-bottom: 0.8pt solid var(--accent);
}

.thesis-list li {
  grid-template-columns: 10mm 1fr;
  gap: 3mm;
  margin: 0;
  padding: 2.4mm 0;
  background: transparent;
  border-left: 0;
  border-bottom: 0.35pt solid var(--soft-line);
}

.thesis-list li:last-child {
  border-bottom: 1pt solid var(--accent);
}

.thesis-number {
  color: var(--accent) !important;
  font-size: 11pt;
  text-align: center;
}

.thesis-copy {
  display: grid;
  grid-template-columns: 31mm minmax(0, 1fr);
  gap: 3mm;
  align-items: baseline;
}

.thesis-copy strong {
  color: var(--ink) !important;
  font-size: 9.4pt;
}

.thesis-copy p {
  margin: 0;
  font-size: 9pt;
}

.metrics-interpretation {
  margin: 0 0 2.5mm;
  padding: 2.5mm 3mm;
  color: #323a43;
  background: var(--soft-surface);
  font-size: 9pt;
  line-height: 1.65;
}

.metrics-interpretation .inline-number,
.section-lead .inline-number,
.interpretation-panel .inline-number,
.valuation-decision-grid .inline-number,
.panel-support .inline-number {
  padding: 0.15mm 0.6mm;
  background: #eef0f2;
  border-radius: 0.45mm;
  box-decoration-break: clone;
  -webkit-box-decoration-break: clone;
}

.section-lead {
  margin: 0 0 2.8mm;
  padding: 0;
  color: #303945;
  background: transparent;
  border-left: 0;
  font-weight: 400;
  font-size: 9.3pt;
}

.section-evidence-grid,
.section-analysis-grid,
.valuation-decision-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: stretch;
  gap: 6mm;
}

.section-analysis-grid-balance {
  grid-template-columns: minmax(0, 0.82fr) minmax(0, 1.18fr);
}

.evidence-panel,
.interpretation-panel,
.valuation-decision-grid > div {
  min-width: 0;
}

.evidence-panel {
  display: flex;
  flex-direction: column;
}

.evidence-panel .table-figure,
.evidence-panel .chart-figure {
  width: 100%;
  margin: 0;
}

.panel-support {
  margin: auto 0 0;
  padding: 2.4mm 0 0;
  color: #3e4650;
  border-top: 0.35pt solid var(--soft-line);
  font-size: 8.6pt;
  line-height: 1.6;
}

.interpretation-panel {
  padding: 3mm 3.4mm;
  background: var(--soft-surface);
  border: 0.35pt solid var(--soft-line);
}

.section-evidence-grid + .interpretation-panel {
  margin-top: 3mm;
}

.interpretation-panel h3,
.valuation-decision-grid h3 {
  margin: 0 0 2mm;
  color: var(--accent);
  font-family: "Heiti SC", "STHeiti", "Microsoft YaHei", sans-serif;
  font-size: 9.2pt;
  font-weight: 700;
}

.interpretation-panel p,
.valuation-decision-grid p {
  margin: 0 0 1.8mm;
  font-size: 8.9pt;
  line-height: 1.66;
  text-align: justify;
  text-indent: 0;
  text-justify: inter-ideograph;
}

.interpretation-panel ul,
.valuation-decision-grid ul {
  margin: 1mm 0 0;
  padding-left: 4.5mm;
  font-size: 8.8pt;
}

.section-valuation > .table-figure {
  margin: 2.5mm 0 3mm;
}

.valuation-decision-grid {
  margin-top: 3mm;
}

.valuation-decision-grid > div {
  padding: 2.8mm 0;
  border-top: 0.7pt solid var(--accent);
  border-bottom: 0.35pt solid var(--hairline);
}

.verification-list li {
  margin-bottom: 1.5mm;
}

.risk-table {
  table-layout: fixed;
  font-size: 7.4pt;
}

.risk-table th:nth-child(1),
.risk-table td:nth-child(1) { width: 16%; }
.risk-table th:nth-child(2),
.risk-table td:nth-child(2) { width: 36%; }
.risk-table th:nth-child(3),
.risk-table td:nth-child(3) { width: 10%; text-align: center; }
.risk-table th:nth-child(4),
.risk-table td:nth-child(4) { width: 10%; text-align: center; }
.risk-table th:nth-child(5),
.risk-table td:nth-child(5) { width: 28%; }

.risk-table tbody tr + tr {
  border-top: 0.35pt solid var(--soft-line);
}

.risk-table tbody th {
  color: var(--ink);
  font-size: 7.7pt;
  font-weight: 700;
}

.risk-importance.severity-high {
  color: var(--negative);
  font-weight: 700;
}

.risk-importance.severity-medium {
  color: var(--warning);
  font-weight: 700;
}

.risk-importance.severity-low {
  color: var(--positive);
  font-weight: 700;
}

.data-limit-note {
  margin: 0;
  color: var(--muted);
  font-size: 8.2pt;
  line-height: 1.6;
  text-align: left;
  text-indent: 0 !important;
}

.metric-table td.tone-positive,
.metric-table td.tone-negative,
.metric-table td.tone-warning,
.data-table td.tone-positive,
.data-table td.tone-negative,
.data-table td.tone-warning {
  background: transparent;
  box-shadow: none;
}

@media screen and (max-width: 820px) {
  html,
  body {
    min-width: 0;
  }

  .document-shell {
    width: 100%;
    min-height: 100vh;
    padding: 24px 18px 28px;
    box-shadow: none;
  }

  .report-navigation {
    margin: 0 -18px;
    padding: 0 18px;
  }

  h1 {
    font-size: 22pt;
  }

  .section-evidence-grid,
  .section-analysis-grid,
  .section-analysis-grid-balance,
  .valuation-decision-grid {
    grid-template-columns: 1fr;
  }

  .market-snapshot {
    min-width: 0;
  }

  .thesis-copy {
    grid-template-columns: 1fr;
    gap: 0.8mm;
  }

  .section-pair {
    grid-template-columns: 1fr;
    gap: 0;
  }

  .risk-list li {
    grid-template-columns: 15mm 1fr;
    gap: 3mm;
  }

  .table-figure table {
    min-width: 680px;
  }

  .risk-table-wrap .risk-table {
    min-width: 900px;
  }
}

@media screen and (max-width: 680px) {
  .title-block.has-market-snapshot {
    grid-template-columns: 1fr;
  }

  .market-snapshot {
    padding: 4mm 0 0;
    border-top: 0.5pt solid var(--hairline);
    border-left: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  html {
    scroll-behavior: auto;
  }

  *,
  *::before,
  *::after {
    transition-duration: 0.01ms !important;
  }
}

@page {
  size: A4;
}

@media print {
  html,
  body {
    width: auto;
    background: #fff;
  }

  .document-shell {
    width: auto;
    min-height: 0;
    margin: 0;
    padding: 0;
    box-shadow: none;
  }

  .report-navigation {
    display: none;
  }

  .source-details > summary {
    display: flex;
    pointer-events: none;
  }

  .source-toggle-button {
    display: none;
  }

  .source-details > *:not(summary) {
    display: block !important;
  }

  .section-pair,
  .chart-figure,
  tr {
    break-inside: avoid;
  }

  .table-figure,
  table {
    break-inside: auto;
  }

  a {
    color: inherit;
  }

  tbody tr:hover,
  .metric-table td.tone-positive,
  .metric-table td.tone-negative,
  .metric-table td.tone-warning,
  .data-table td.tone-positive,
  .data-table td.tone-negative,
  .data-table td.tone-warning {
    background: transparent;
  }
}

/* ==================== a17 行业研究报告 覆盖 ==================== */

/* 视觉外壳微调：机构风格基座，外壳仅调 accent 与版心密度 */
body.visual-data-manual {
  --accent: #17365d;
}

body.visual-analysis-note {
  --accent: #173653;
}

body.visual-deep-research {
  --accent: #7c2d12;
}

body.density-compact {
  font-size: 9.8pt;
  line-height: 1.55;
}

body.density-detailed {
  font-size: 11.2pt;
  line-height: 1.7;
}

/* 封面（契约：draft-watermark < eyebrow；meta-grid 固定 5 列）——插件式紧凑标题块 */
.cover {
  position: relative;
  padding: 6mm 0 2mm;
  page-break-after: always;
}

.cover .title-block {
  padding: 0;
}

.cover .title-copy {
  min-width: 0;
}

.cover .eyebrow {
  margin: 0 0 3mm;
  color: var(--accent);
  font-family: "Heiti SC", "STHeiti", "Microsoft YaHei", sans-serif;
  font-size: 9.5pt;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.cover h1 {
  max-width: none;
  margin: 0 0 3.2mm;
  color: #101820;
  font-size: 24pt;
  line-height: 1.28;
}

.cover .report-deck {
  max-width: none;
  margin: 0;
  padding: 0;
  color: #28323d;
  border-left: 0;
  font-size: 10.4pt;
  font-weight: 400;
  line-height: 1.72;
  text-align: justify;
  text-justify: inter-ideograph;
}

.meta-grid {
  margin-top: 6mm;
  display: grid;
  grid-template-columns:repeat(5,1fr);
  gap: 3mm;
}

.meta {
  border: 1px solid var(--hairline);
  border-radius: 2mm;
  padding: 3mm 3.5mm;
  background: var(--paper);
}

.meta span {
  display: block;
  color: var(--muted);
  font-size: 7.5pt;
}

.meta strong {
  display: block;
  margin-top: 1mm;
  overflow-wrap: anywhere;
}

/* 视觉编排说明 */
.visual-note {
  margin-top: 5mm;
  padding: 2.5mm 3mm;
  color: var(--muted);
  background: var(--soft-surface);
  border-left: 2pt solid var(--hairline);
  font-size: 8pt;
  line-height: 1.6;
}

.visual-note strong {
  color: var(--ink);
}

/* toc */
.toc {
  columns: 2;
  column-gap: 36px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.toc li {
  break-inside: avoid;
  padding: 1.5mm 0;
  border-bottom: 0.35pt dotted var(--hairline);
}

.toc a {
  color: inherit;
  text-decoration: none;
}

/* chart-directory */
.chart-directory {
  margin-top: 6mm;
}

/* 章节 */
.chapter {
  break-before: page;
}

.chapter-summary {
  margin: 0 0 3mm;
  padding: 2.6mm 3.2mm;
  color: #334155;
  background: var(--soft-surface);
  border-left: 2pt solid var(--hairline);
  font-size: 10pt;
}

/* 图表内联（精简风，贴近插件：无边框卡片，图注用 figcaption 样式） */
.chart {
  margin: 4mm 0;
  break-inside: avoid;
}

.chart svg {
  display: block;
  width: 100%;
  height: auto;
  overflow: visible;
}

.chart figcaption {
  margin-top: 1.8mm;
  color: var(--ink);
  font-size: 9pt;
  font-weight: 650;
  text-align: center;
}

.chart-number {
  color: var(--ink);
  font-weight: 700;
}

.chart-pie,
.chart-radar {
  width: 64%;
  margin-left: auto;
  margin-right: auto;
}

/* 引用与证据 */
.reference {
  margin-top: 1.5mm;
  color: var(--muted);
  font-size: 7.5pt;
}

.citation {
  margin-right: 1.5mm;
  color: var(--accent);
  text-decoration: none;
  border-bottom: 0.5pt dotted var(--hairline);
}

/* 不确定性提示 */
.uncertainty {
  margin: 3mm 0;
  padding: 2.5mm 3mm;
  background: var(--warning-surface);
  border: 0.7pt solid #d9b34a;
  border-radius: 2mm;
  break-inside: avoid;
}

.uncertainty strong {
  color: #92400e;
}

/* 草稿标记 */
.draft-watermark {
  position: absolute;
  inset: 0;
  z-index: 5;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
  color: #dc2626;
  font-size: 60pt;
  font-weight: 900;
  letter-spacing: 0.3em;
  opacity: 0.08;
  transform: rotate(-20deg);
}

.draft-banner {
  margin-bottom: 4mm;
  padding: 3mm 4mm;
  color: var(--negative);
  background: var(--negative-surface);
  border: 1pt solid var(--negative);
  border-radius: 2mm;
}

.draft-banner strong {
  color: var(--negative);
}

/* 风险/边界列表 */
.risk-list,
.boundary-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.risk-list li,
.boundary-list li {
  display: block;
  margin: 1.5mm 0;
  padding: 2.5mm 3mm;
  background: var(--soft-surface);
  border-left: 2pt solid var(--hairline);
}

/* 附录 */
.risk-appendix,
.quality-appendix,
.source-index {
  break-before: page;
}

.source-index table {
  font-size: 7pt;
}

/* 质量表 = 三线表（与 data-table 合并选择器复用） */
.quality-table {
  table-layout: fixed;
}

.quality-table tbody tr + tr {
  border-top: 0.35pt solid var(--soft-line);
}

/* 页脚 */
.footer-note {
  margin-top: 7mm;
  padding-top: 3mm;
  color: var(--muted);
  border-top: 1px solid var(--rule);
  font-size: 7pt;
}

/* 执行摘要组件 */
.headline {
  margin: 0 0 3mm;
  font-size: 12pt;
  font-weight: 700;
  line-height: 1.6;
  text-indent: 0 !important;
}

.conclusion {
  margin: 2mm 0;
  padding: 2.6mm 3.2mm;
  background: var(--soft-surface);
  border-left: 2pt solid var(--accent);
}

.conclusion strong {
  color: var(--ink);
  font-family: "Heiti SC", "STHeiti", "Microsoft YaHei", sans-serif;
  font-size: 9.4pt;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 1.5mm;
  margin-top: 1.5mm;
}

.chip {
  padding: 0.5mm 1.8mm;
  color: #334155;
  background: #e2e8f0;
  border-radius: 999px;
  font-size: 7pt;
}

.chip.citation {
  text-decoration: none;
}

/* 目录放在吸顶导航内，双栏展示 */
.report-navigation ol.toc {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 10mm;
  padding: 2mm 0;
}

.report-navigation ol.toc a {
  min-height: 0;
  padding: 1.2mm 0;
}

@media print {
  main {
    max-width:none;
    padding: 0;
  }

  .visual-data-manual main,
  .visual-deep-research main {
    max-width:none;
    padding: 0;
  }

  .density-compact main,
  .density-detailed main {
    padding-top: 0;
    padding-bottom: 0;
  }

  .report-navigation {
    display: block;
    position: static;
  }

  .cover {
    min-height: 245mm;
  }
}

    @page {
      size: A4;
      @bottom-center {
        content:"中国光伏制造行业研究报告 · " counter(page);
        color: #64748b;
        font-size: 9pt;
      }
    }
  `;
