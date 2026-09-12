from prettyplay import PrettyPlay


def test_google_search(play: PrettyPlay):
    play.step('Open https://google.com')
    play.step('Find results for "UI testing automation"')

    play.expect('The results page contains the text "test"')
