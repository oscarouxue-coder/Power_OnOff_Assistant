"""Read-only document/link and touched-source whitespace checks for this stage."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[2]
documents = ('PROJECT_STATUS.md', 'DEVELOPMENT_LOG.md', 'ACCEPTANCE_BASELINE.md', 'CAPABILITY_COVERAGE.md',
             '.claude/plans/full-capability-agent.md', 'Cheating_machine_execution_tool/line_check_assistant_README.md',
             'validation/full_capability_agent_20261115/IMPLEMENTATION.md')
checked = 0
for name in documents:
    path = root / name
    text = path.read_text(encoding='utf-8-sig')
    # Historical logs contain code examples and old links. Review this stage's
    # edited sections rather than treating them as new documentation defects.
    if name == 'DEVELOPMENT_LOG.md':
        text = text.split('## 2026-11-16 - 补齐配置事务与多通道业务', 1)[1].split('\n## ', 1)[0]
    elif name == 'PROJECT_STATUS.md':
        text = text.split('最新Full Capability Agent阶段4续接', 1)[1].split('\n\n', 1)[0]
    elif name == 'ACCEPTANCE_BASELINE.md':
        text = '\n'.join(line for line in text.splitlines() if 'Full Capability Agent阶段4' in line or line.startswith('- Full Capability Agent：'))
    elif name.endswith('line_check_assistant_README.md'):
        text = text.split('## AI正式业务能力', 1)[1].split('\n## ', 1)[0]
    for target in re.findall(r'\[[^\]\n]+\]\(([^)\n]+)\)', text):
        target = target.strip('<>').split('#', 1)[0]
        if not target or re.match(r'(https?|mailto|app|plugin):', target):
            continue
        assert (path.parent / target).exists(), (name, target)
        checked += 1
assert '已有接口 63 项；部分接入 15 项；待接入 5 项；人工控制面 3 项' in (root / 'CAPABILITY_COVERAGE.md').read_text(encoding='utf-8')
for name in ('capability_channel_service.py', 'capability_notification_service.py', 'capability_settings_service.py', 'ai_business_batch_route.py'):
    path = root / 'Cheating_machine_execution_tool/src/services' / name
    assert all(line.rstrip() == line for line in path.read_text(encoding='utf-8').splitlines()), name
print(f'STAGE4_DOCUMENTS_OK: {len(documents)} UTF-8 documents, {checked} local links, coverage counts and new source whitespace')
