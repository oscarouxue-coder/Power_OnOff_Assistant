"""Project the original AI log summaries into the Qt live log."""
from dataclasses import replace

from src.ui.main_log_filter import ai_main_log_tag, format_main_log_message, is_ai_log_message


AI_LEVELS = {'warning': 'WARN', 'error': 'ERROR', 'success': 'SUCCESS'}


def project_live_log(entry):
    """Pure, thread-safe display projection. The caller persists the original."""
    if entry.raw or not is_ai_log_message(entry.message):
        return entry
    try:
        message = format_main_log_message(entry.message)
    except (RecursionError, OverflowError):
        return entry
    if message is None:
        # A producer's explicit severity takes precedence over a known routine pattern.
        return entry if entry.level in ('WARN', 'ERROR') else None
    level = AI_LEVELS.get(ai_main_log_tag(message), entry.level)
    if entry.level == 'ERROR' or entry.level == 'WARN' and level != 'ERROR':
        level = entry.level
    return replace(entry, message=message, level=level)
