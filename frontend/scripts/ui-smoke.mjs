import { readFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

const ROOT = path.resolve(process.cwd());

const checks = [
  {
    file: 'src/views/LoginView.js',
    contains: ['id="auth-submit"', 'id="auth-email"', 'id="auth-password"'],
  },
  {
    file: 'src/views/ClassView.js',
    contains: ['id="btn-create-class"', 'id="btn-import-students"', 'id="btn-export-att"', 'id="btn-archive"'],
  },
  {
    file: 'src/views/WorkflowView.js',
    contains: [
      'id="btn-create-unit"',
      'id="btn-start-session"',
      'id="btn-end-session"',
      'id="btn-save-attendance"',
      'id="btn-checklist-expand-all"',
    ],
  },
  {
    file: 'src/views/ExamView.js',
    contains: ['id="btn-create-exam"', 'id="btn-import-results"', 'id="btn-export-results"', 'id="btn-edit-exam"'],
  },
  {
    file: 'src/views/OwnerView.js',
    contains: ['id="btn-create-teacher"', 'id="btn-change-pwd"', 'btn-assign-teacher'],
  },
  {
    file: 'src/views/CalendarView.js',
    contains: [
      'id="btn-prev-week"',
      'id="btn-next-week"',
      'id="btn-this-week"',
      'id="btn-export-cal"',
      'data-slot-plus-day',
      'quick-action-allow-holiday',
      'is-holiday-blocked',
    ],
  },
];

const buttonAuditFiles = [
  'src/components/AppShell.js',
  'src/views/LoginView.js',
  'src/views/ClassView.js',
  'src/views/WorkflowView.js',
  'src/views/CalendarView.js',
  'src/views/ExamView.js',
  'src/views/OwnerView.js',
];

function stripTemplateExpressions(value) {
  return value.replace(/\$\{[^}]*\}/g, '__DYNAMIC__');
}

function auditButtonLabels(file, text) {
  const issues = [];
  const pattern = /<button\b([^>]*)>([\s\S]*?)<\/button>/g;
  let match;
  while ((match = pattern.exec(text)) !== null) {
    const attrs = String(match[1] || '');
    const rawInner = String(match[2] || '');
    const hasAriaLabel = /aria-label\s*=/.test(attrs);
    const inner = stripTemplateExpressions(rawInner)
      .replace(/<[^>]*>/g, '')
      .replace(/\s+/g, ' ')
      .trim();
    const hasDynamicContent = inner.includes('__DYNAMIC__');
    if (hasDynamicContent) continue;
    if (!inner && !hasAriaLabel) {
      issues.push('Button without visible text or aria-label');
      continue;
    }
    if (inner && !/[A-Za-z]/.test(inner) && !hasAriaLabel) {
      issues.push(`Potential icon-only button label: "${inner}"`);
    }
  }
  return issues;
}

async function run() {
  const failures = [];

  for (const check of checks) {
    const absPath = path.join(ROOT, check.file);
    const text = await readFile(absPath, 'utf8');
    const missing = check.contains.filter(token => !text.includes(token));
    if (missing.length) {
      failures.push({ file: check.file, missing });
      continue;
    }
    console.log(`[OK] ${check.file}`);
  }

  for (const file of buttonAuditFiles) {
    const absPath = path.join(ROOT, file);
    const text = await readFile(absPath, 'utf8');
    const issues = auditButtonLabels(file, text);
    if (issues.length) {
      failures.push({ file, missing: issues });
      continue;
    }
    console.log(`[OK] ${file} button-label audit`);
  }

  if (!failures.length) {
    console.log('[OK] UI smoke checks passed');
    return;
  }

  for (const failure of failures) {
    console.error(`[FAIL] ${failure.file}`);
    for (const token of failure.missing) {
      console.error(`  - Missing token: ${token}`);
    }
  }
  process.exitCode = 1;
}

run().catch(err => {
  console.error('[FAIL] UI smoke checks crashed');
  console.error(err?.stack || String(err));
  process.exitCode = 1;
});
