import re

# Экранирование под Telegram MarkdownV2
_TELEGRAM_MD_V2_SPECIALS = r'[_*\[\]()~`>#+\-=|{}.!]'

def escape_markdown_v2(text: str) -> str:
    if not text:
        return text
    return re.sub(r'([%s])' % re.escape(_TELEGRAM_MD_V2_SPECIALS), r'\\\1', text)
