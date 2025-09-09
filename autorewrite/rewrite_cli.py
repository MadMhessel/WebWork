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
