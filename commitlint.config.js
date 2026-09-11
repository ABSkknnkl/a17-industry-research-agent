/**
 * commitlint 配置 —— a17-industry-research-agent（4 人协作版 v1.0）
 *
 * 服务端第二道闸：本地钩子可以被 --no-verify 绕过，这里绕不过去。
 * 在 CI 中对 PR 的每一条提交逐条校验。
 *
 * 强制格式： <type>(<scope>): <姓名> <subject>
 *   例：fix(backend): 张三 修复 evidence_items 空列表导致 A2 覆盖循环崩溃
 *
 * 安装：
 *   npm install --save-dev @commitlint/cli @commitlint/config-conventional
 *   npx husky init
 *   echo 'npx --no-install commitlint --edit "$1"' > .husky/commit-msg
 */

const fs = require('fs');
const path = require('path');

/** 团队名单（与 .githooks/team.txt 保持一致） */
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

/** 是否采用「姓名开头」格式：张三：feat(backend) 修复xxx */
const AUTHOR_FIRST = false;

/** 允许的 type */
const TYPES = [
  'feat', 'fix', 'refactor', 'perf', 'test',
  'docs', 'build', 'ci', 'chore', 'revert',
];

/** 允许的 scope */
const SCOPES = [
  'backend', 'frontend', 'contracts', 'eval', 'docs',
  'agent1', 'agent2', 'agent3', 'agent4', 'agent5',
  'linter', 'charts', 'deps', 'release',
];

/** 命中即拒绝的提交信息 */
const FORBIDDEN = [
  [/^\d+$/, '纯数字提交信息'],
  [/^[a-zA-Z]{1,2}$/, '单字母/双字母提交信息'],
  [/^(新的|测试|更新|修改|提交|备份|保存|整理)$/, '无信息量的中文单词'],
  [/(你是一个|你的任务是|请按照以下|负责对本代码|作为一[位个])/, 'AI Prompt 原文泄漏'],
  [/pre-?termination/i, '会话中断救急提交，请用 git stash'],
  [/^(backup|save|tmp|temp|checkpoint|wip)$/i, '无意义备份提交'],
];

module.exports = {
  extends: ['@commitlint/config-conventional'],

  plugins: [
    {
      rules: {
        /** 作者姓名校验 + 垃圾信息拦截 */
        'require-author': (parsed) => {
          const header = (parsed.header || '').trim();

          if (!header) return [false, '提交信息不能为空'];

          for (const [re, desc] of FORBIDDEN) {
            if (re.test(header)) {
              return [false, `提交信息被拒绝（${desc}）："${header}"`];
            }
          }

          // 解析姓名：type(scope): 姓名 subject  |  姓名：type(scope) subject
          let name = null;
          if (AUTHOR_FIRST) {
            const m = header.match(/^([^：:]+)[：:]/);
            name = m ? m[1].trim() : null;
          } else {
            const m = header.match(
              /^(?:feat|fix|refactor|perf|test|docs|build|ci|chore|revert)(?:\([^)]*\))?:\s*([^\s]+)\s+\S/
            );
            name = m ? m[1] : null;
          }

          if (!name) {
            return [
              false,
              `未解析出作者姓名。格式应为 "${AUTHOR_FIRST ? '张三：feat(backend) 描述' : 'feat(backend): 张三 描述'}"\n  实际内容："${header}"`,
            ];
          }

          if (TEAM.length > 0 && !TEAM.includes(name)) {
            return [
              false,
              `作者「${name}」不在团队名单中。当前名单：${TEAM.join(' / ')}\n` +
                `  提示：提交信息里的姓名必须与 .githooks/team.txt 一致`,
            ];
          }

          // 描述长度
          const subject = header.replace(/^[^:：]+[：:]\s*/, '').replace(/^\S+\s+/, '');
          const cjk = (subject.match(/[一-龥]/g) || []).length;
          if (cjk > 0 && cjk < 4) {
            return [false, `描述过于简略（${cjk} 个汉字，最少 4 个）："${subject}"`];
          }

          return [true];
        },
      },
    },
  ],

  rules: {
    'require-author': [2, 'always'],
    'type-enum': [2, 'always', TYPES],
    'scope-enum': [1, 'always', SCOPES],
    'subject-empty': [2, 'never'],
    'subject-full-stop': [2, 'never', '.。'],
    'header-max-length': [2, 'always', 120],
    'body-max-line-length': [1, 'always', 100],
    'body-empty': [1, 'never'],
  },
};
