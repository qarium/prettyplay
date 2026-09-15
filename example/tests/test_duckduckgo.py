from prettyplay import PrettyPlay


def test_duckduckgo_search(play: PrettyPlay):
    play.step('Open https://duckduckgo.com')
    play.step('Find results for "UI testing automation"')

    play.expect('The results page contains the text "test"')
