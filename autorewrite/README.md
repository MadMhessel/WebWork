# autorewrite

Автономный и быстрый рерайт новостных постов (без внешних ИИ-API). Подходит для Telegram-бота.

## Возможности

- Рерайт в 3 этапа (фолбэк-цепочка): мягкий → компрессия → усиленный.
- Синонимизация/перефраз, перестановки, шаблоны новостного стиля.
- Контроль длины (под лимит Telegram 4096).
- Экранирование MarkdownV2.
- Антидубликаты: шинглы (Jaccard) + SimHash (Хэмминг).
- Простое API и CLI.

## Установка

```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .\.venv\Scripts\activate
pip install -e .
```

### CLI

```
python rewrite_cli.py --input "Текст новости..." --max-chars 3500 --min-distance 16
```

Или из файла:

```
python rewrite_cli.py --file input.txt
```

Вывод: JSON с полями title, text, similarity, distance, warnings.

### Python API

```python
from rewriter.pipeline import rewrite_post

res = rewrite_post(
    text="Изначальный пост...",
    desired_len=3500,
    min_hamming_distance=16,  # SimHash
    max_jaccard=0.85           # допустимая схожесть по шинглам
)

print(res["title"])
print(res["text"])
print(res["similarity"])
print(res["distance"])
print(res["warnings"])
```

### Интеграция с Telegram

Используйте `rewriter.markdown.escape_markdown_v2(text)` перед отправкой сообщения.
Следите за длиной: параметр `desired_len` в `rewrite_post`.

### Настройка

Словарь синонимов и шаблонов — в `rewriter/rules.py`. Расширяйте под собственный стиль/тематику (строительство, НН-регион).

## `rewrite_cli.py`

```python
import argparse
import json
import sys
from rewriter.pipeline import rewrite_post

def main():
    parser = argparse.ArgumentParser(description="Автономный рерайт новостных постов")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--input", type=str, help="Входной текст")
    g.add_argument("--file", type=str, help="Путь к текстовому файлу UTF-8")
    parser.add_argument("--max-chars", type=int, default=3500, help="Максимальная длина результата")
    parser.add_argument("--min-distance", type=int, default=16, help="Мин. дистанция SimHash (0..64)")
    parser.add_argument("--max-jaccard", type=float, default=0.85, help="Макс. схожесть Jaccard по шинглам (0..1)")
    parser.add_argument("--title-len", type=int, default=110, help="Желаемая длина заголовка")
    args = parser.parse_args()

    if args.input:
        text = args.input
    else:
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception as e:
            print(json.dumps({"error": f"Не удалось прочитать файл: {e}"}), ensure_ascii=False)
            sys.exit(1)

    res = rewrite_post(
        text=text,
        desired_len=args.max_chars,
        min_hamming_distance=args.min_distance,
        max_jaccard=args.max_jaccard,
        desired_title_len=args.title_len,
    )

    print(json.dumps(res, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
```

### Как подключить к вашему боту

Установите пакет (локально в вашем проекте):

```
pip install -e /путь/к/autorewrite
```

В коде бота используйте:

```python
from rewriter.pipeline import rewrite_post
from rewriter.markdown import escape_markdown_v2

def rewrite_and_prepare(text: str) -> str:
    res = rewrite_post(
        text=text,
        desired_len=3500,
        min_hamming_distance=18,
        max_jaccard=0.80,
        desired_title_len=100,
    )
    # формируем пост для Telegram (заголовок жирным)
    title = res["title"]
    body = res["text"]
    msg = f"*{title}*\n\n{body}"
    return escape_markdown_v2(msg)
```

Если у вас включена модерация — сохраняйте вместе с результатом метрики similarity и warnings, чтобы оператор видел причину фолбэка.

### Почему это работает быстро и офлайн

Никаких внешних API и моделей — только stdlib.
Рерайт основан на детерминированных правилах и простых эвристиках для новостей.
Антидубликаты — простые, но эффективные метрики (шинглы + SimHash).

### Что можно улучшить (по желанию)

- Расширить словарь SYNONYMS и PATTERNS под вашу лексику (строительство, НН-регион).
- Добавить небольшой доменный классификатор (ключевые слова) перед рерайтом, чтобы не тратить ресурсы на нерелевантные тексты.
- Подключить опциональный “тяжёлый” перефразер (например, локальную ONNX-модель) как дополнительный этап до/после правил — модуль легко расширяем.

Если хотите — добавлю классификатор “Стройка+Нижегородская область” и связывающий код с вашими антидубликатами и модерацией.
