from prettyplay import PrettyPlay


def test_yandex_search(play: PrettyPlay):
    play.step('Open https://ya.ru')
    play.step('Find results for "автоматизация UI тестирования"')

    play.expect('The results page contains the text "тест"')
