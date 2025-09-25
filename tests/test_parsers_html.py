import pytest

from parsers import html as html_parsers

HTML_FIXTURES = {
    "minstroy.nobl.ru": (
        "<article><h1 class='page-title'>Минстрой запускает проект</h1>"
        "<div class='intro'><p>Краткий анонс Минстрой</p></div>"
        "<time datetime='2025-01-01T10:00:00'>1 января</time>"
        "<div class='article-body'><p>Первый абзац Минстрой.</p><p>Второй абзац.</p></div></article>",
        "Минстрой запускает проект",
        "Краткий анонс Минстрой",
        "2025-01-01T10:00:00",
    ),
    "mingrad.nobl.ru": (
        "<article><h1 class='post-title'>Минград представил план</h1>"
        "<div class='intro'><p>Вводная часть Минград</p></div>"
        "<time datetime='2025-01-02T11:00:00'>2 января</time>"
        "<div class='post-content'><p>Первый абзац Минград.</p><p>Дополнение.</p></div></article>",
        "Минград представил план",
        "Вводная часть Минград",
        "2025-01-02T11:00:00",
    ),
    "newsnn.ru": (
        "<article><h1 class='article__title'>NewsNN сообщает</h1>"
        "<div class='article__lead'>Важная новость NewsNN</div>"
        "<time datetime='2025-01-03T12:00:00'>3 января</time>"
        "<div class='article__body'><p>Текст NewsNN.</p></div></article>",
        "NewsNN сообщает",
        "Важная новость NewsNN",
        "2025-01-03T12:00:00",
    ),
    "nn.ru": (
        "<article><h1 class='article__title'>NN.RU рассказывает</h1>"
        "<div class='article__lead'>Анонс NN.RU</div>"
        "<time datetime='2025-01-04T09:00:00'>4 января</time>"
        "<div class='article__text'><p>Материал NN.RU.</p></div></article>",
        "NN.RU рассказывает",
        "Анонс NN.RU",
        "2025-01-04T09:00:00",
    ),
    "domostroynn.ru": (
        "<article><h1 class='news-detail__title'>Домострой обновил раздел</h1>"
        "<div class='news-detail__lead'>Кратко Домострой</div>"
        "<time datetime='2025-01-05T08:00:00'>5 января</time>"
        "<div class='news-detail__content'><p>Контент Домострой.</p></div></article>",
        "Домострой обновил раздел",
        "Кратко Домострой",
        "2025-01-05T08:00:00",
    ),
    "kommersant.ru": (
        "<article><h1 class='article_name'>Коммерсант сообщил</h1>"
        "<div class='article_subheader'>Лид Коммерсанта</div>"
        "<time datetime='2025-01-06T07:00:00'>6 января</time>"
        "<div class='article_text'><p>Текст Коммерсанта.</p></div></article>",
        "Коммерсант сообщил",
        "Лид Коммерсанта",
        "2025-01-06T07:00:00",
    ),
    "nn.rbc.ru": (
        "<article><h1 class='article__header'>РБК НН объявил</h1>"
        "<div class='article__subtitle'>Лид РБК</div>"
        "<time datetime='2025-01-07T06:00:00'>7 января</time>"
        "<div class='article__content'><p>Текст РБК.</p></div></article>",
        "РБК НН объявил",
        "Лид РБК",
        "2025-01-07T06:00:00",
    ),
    "vgoroden.ru": (
        "<article><h1 class='article-title'>В городе N описал</h1>"
        "<div class='article-lead'>Лид В городе N</div>"
        "<time datetime='2025-01-08T05:00:00'>8 января</time>"
        "<div class='article-body'><p>Текст В городе N.</p></div></article>",
        "В городе N описал",
        "Лид В городе N",
        "2025-01-08T05:00:00",
    ),
    "nta-pfo.ru": (
        "<article><h1 class='news-detail__title'>НТА-ПФО сообщает</h1>"
        "<div class='news-detail__lead'>Лид НТА-ПФО</div>"
        "<time datetime='2025-01-09T04:00:00'>9 января</time>"
        "<div class='news-detail__content'><p>Текст НТА-ПФО.</p></div></article>",
        "НТА-ПФО сообщает",
        "Лид НТА-ПФО",
        "2025-01-09T04:00:00",
    ),
    "gipernn.ru": (
        "<article><h1 class='article__title'>ГИПЕРНН написал</h1>"
        "<div class='article__lead'>Лид ГИПЕРНН</div>"
        "<time datetime='2025-01-10T03:00:00'>10 января</time>"
        "<div class='article__content'><p>Текст ГИПЕРНН.</p></div></article>",
        "ГИПЕРНН написал",
        "Лид ГИПЕРНН",
        "2025-01-10T03:00:00",
    ),
    "admgor.nnov.ru": (
        "<article><h1 class='article-title'>Администрация сообщает</h1>"
        "<div class='lead'>Лид администрации</div>"
        "<time datetime='2025-01-12T01:00:00'>12 января</time>"
        "<div class='article-body'><p>Текст администрации.</p></div></article>",
        "Администрация сообщает",
        "Лид администрации",
        "2025-01-12T01:00:00",
    ),
    "gsn.nobl.ru": (
        "<article><h1 class='news-detail__title'>Госстройнадзор информирует</h1>"
        "<div class='news-detail__lead'>Лид ГСН</div>"
        "<time datetime='2025-01-13T10:30:00'>13 января</time>"
        "<div class='news-detail__content'><p>Текст ГСН.</p></div></article>",
        "Госстройнадзор информирует",
        "Лид ГСН",
        "2025-01-13T10:30:00",
    ),
    "52.mchs.gov.ru": (
        "<article><h1 class='article__title'>МЧС сообщает о происшествии</h1>"
        "<div class='article__lead'>Кратко МЧС</div>"
        "<time datetime='2025-01-14T08:45:00'>14 января</time>"
        "<div class='article__content'><p>Текст МЧС.</p></div></article>",
        "МЧС сообщает о происшествии",
        "Кратко МЧС",
        "2025-01-14T08:45:00",
    ),
    "strategy.nobl.ru": (
        "<article><h1 class='article-title'>Стратегия НО описывает проект</h1>"
        "<div class='intro'>Лид Стратегии</div>"
        "<time datetime='2025-01-15T12:15:00'>15 января</time>"
        "<div class='article-body'><p>Текст Стратегии.</p></div></article>",
        "Стратегия НО описывает проект",
        "Лид Стратегии",
        "2025-01-15T12:15:00",
    ),
    "nizhstat.gks.ru": (
        "<article><h1 class='article-title'>Нижегородстат публикует отчёт</h1>"
        "<div class='intro'>Кратко Нижегородстат</div>"
        "<time datetime='2025-01-16T09:20:00'>16 января</time>"
        "<div class='article-body'><p>Текст Нижегородстат.</p></div></article>",
        "Нижегородстат публикует отчёт",
        "Кратко Нижегородстат",
        "2025-01-16T09:20:00",
    ),
    "vremyan.ru": (
        "<article><h1 class='article-title'>Время Н передает</h1>"
        "<div class='article-lead'>Лид Время Н</div>"
        "<time datetime='2025-01-11T02:00:00'>11 января</time>"
        "<div class='article-body'><p>Текст Время Н.</p></div></article>",
        "Время Н передает",
        "Лид Время Н",
        "2025-01-11T02:00:00",
    ),
}


@pytest.mark.parametrize("domain", sorted(HTML_FIXTURES.keys()))
def test_parse_article_returns_expected_fields(domain):
    html, expected_title, expected_lead, expected_date = HTML_FIXTURES[domain]
    html_wrapped = f"<html><body>{html}</body></html>"
    result = html_parsers.parse_article(html_wrapped, domain)
    assert result["title"] == expected_title
    assert result["lead"] == expected_lead
    assert result["content"]
    assert result["published_at"] == expected_date
