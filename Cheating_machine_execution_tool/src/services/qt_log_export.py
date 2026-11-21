"""Persist a local operator's bounded log selection to a new text file."""
from pathlib import Path
import os
import tempfile


def export_log_snapshot(destination, scope, entries):
    path = Path(destination)
    if not path.is_absolute() or path.suffix.lower() != '.txt':
        raise ValueError('请选择绝对路径下的新 .txt 日志文件')
    if not entries:
        raise ValueError('当前筛选没有可导出的日志')
    # Publish only after the write succeeds. Never replace another file, even
    # if it was created after the operator picked the destination.
    output = tempfile.NamedTemporaryFile(mode='w', encoding='utf-8-sig', newline='\n',
                                         prefix='.dutpilot-log-', dir=path.parent, delete=False)
    pending = Path(output.name)
    try:
        with output:
            output.write('DUTPilot · 日志筛选记录\n' + scope + '\n\n')
            for row in entries:
                if row.raw:
                    output.write(row.message + '\n')
                    continue
                origin = '项目=' + (row.project_id or '全局')
                if row.run_id:
                    origin += ' 任务=' + row.run_id
                if row.channel is not None:
                    origin += f' 通道=CH{row.channel:02d}'
                output.write(f'{row.time}   {row.level:<5}   [{row.project_name}] [{origin}]  {row.message}\n')
        if os.name == 'nt':
            pending.rename(path)
        else:
            os.link(pending, path)
    except FileExistsError:
        raise ValueError('文件已存在，请选择新的文件名') from None
    finally:
        pending.unlink(missing_ok=True)
    return len(entries)
