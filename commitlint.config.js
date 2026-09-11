/**
 * commitlint 配置 —— a17-industry-research-agent（宽松协作版）
 *
 * 设计原则（按团队反馈调整）：
 * - 姓名 / 格式 / AI prompt 原文：直接放行，不拒绝
 * - 仍拦截：仅纯数字 / 空提交
 *
 * 服务端 CI 用；本地可用 --no-verify。
 */

const fs = require('fs');
const path = require('path');

/** 团队名单（可选，用于提醒，不强制） */
function loadTeam() {
  try {
    const p = path.join(__dirname, '.githooks', 'team.txt');
    return fs.readFileSync(p, 'utf8')
      .split('\n')
      .map((s) => s.trim())
      .filter((s) => s && !s.startsWith('#'));
  } catch {
    return [];
  }
}
const TEAM = loadTeam();

/** 允许的 type（仅建议，不强制枚举） */
const TYPES = [
  'feat', 'fix', 'refactor', 'perf', 'test',
  'docs', 'build', 'ci', 'chore', 'revert',
];

/** 仍拒绝：仅纯数字 / 短字母（AI prompt 原文已放行） */
const FORBIDDEN = [
  [/^\d+$/, '纯数字提交信息'],
  [/^[a-zA-Z]{1,2}$/, '单字母/双字母提交信息'],
  [/^(新的|测试|更新|修改|提交|备份|保存|整理)$/, '无信息量的中文单词'],
];

module.exports = {
  rules: {
    // 自定义：只硬拦垃圾信息；格式/名单/长度一律 warning
    'require-author': [1, 'always'],
    'type-enum': [1, 'always', TYPES],
    'subject-empty': [2, 'never'],
    'subject-full-stop': [1, 'never', '.。'],
    'header-max-length': [1, 'always', 120],
    'body-max-line-length': [0, 'always', 100],
    'body-empty': [0, 'never'],
  },
  plugins: [
    {
      rules: {
        'require-author': (parsed) => {
          const header = (parsed.header || '').trim();
          if (!header) return [false, '提交信息不能为空'];

          for (const [re, desc] of FORBIDDEN) {
            if (re.test(header)) {
              return [false, `提交信息被拒绝（${desc}）："${header}"`];
            }
          }

          // 格式不匹配：warning（level 由 rules 控制；这里返回 true 继续）
          const m = header.match(
            /^(?:feat|fix|refactor|perf|test|docs|build|ci|chore|revert)(?:\([^)]*\))?:\s*([^\s]+)\s+\S/
          );
          if (!m) {
            return [true, `建议格式 type(scope): 姓名 描述 —— 当前："${header}"（不强制）`];
          }
          const name = m[1];
          if (TEAM.length > 0 && !TEAM.includes(name)) {
            return [true, `姓名「${name}」不在 team.txt（不强制，仅提醒）`];
          }
          return [true];
        },
      },
    },
  ],
};
