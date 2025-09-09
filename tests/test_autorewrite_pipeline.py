import os
import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from autorewrite.rewriter.pipeline import rewrite_post


EXAMPLE_TEXT = (
    "В Городецком муниципальном округе Нижегородской области ввели в эксплуатацию новый пункт контроля проезда грузового транспорта, построенный в рамках национального проекта «Инфраструктура для жизни». "
    "Кроме того, водителям транспортных средств доступен сервис информирования о зафиксированных весогабаритных параметрах, воспользовавшись которым можно узнать результаты измерений своего транспортного средства. "
    "При проезде через пункт контроля вес и габариты грузовиков определяются автоматически. При фиксации нарушений информация поступает в центр обработки, где выносится постановление о привлечении к административной ответственности. "
    "Превышение допустимой нагрузки на ось транспортного средства свыше 10 тонн влечет наложение штрафа на собственника большегруза в размере до 600 тысяч рублей. Проект реализуют поэтапно."
)


def test_rewrite_example_behaviour():
    res = rewrite_post(EXAMPLE_TEXT)
    text = res["text"]
    assert "Нижегородской области" in text
    assert "грузового транспорта" in text
    assert "штраф" in text
    for lead in ["Коротко:", "Главное:", "Суть:", "Что произошло:"]:
        assert lead not in text
    assert text.endswith(".")
    assert "  " not in text
    assert ".." not in text
    sim = res["similarity"]
    max_j = float(os.getenv("REWRITE_MAX_JACCARD", "0.72"))
    min_h = int(os.getenv("REWRITE_MIN_HAMMING", "16"))
    assert sim["jaccard"] <= max_j
    assert sim["hamming"] >= min_h or res["warnings"]


def test_geo_and_typos_normalization():
    src = "В Нижегородском регионе начался капитальный ремонт дороги для грузового ."
    res = rewrite_post(src)
    text = res["text"]
    assert "Нижегородской области" in text
    assert "грузового транспорта" in text
    assert "  " not in text
    assert ".." not in text
