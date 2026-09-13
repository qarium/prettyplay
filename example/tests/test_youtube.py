from prettyplay import PrettyPlay


def test_example(play: PrettyPlay):
    play.step('Open https://youtube.com')

    play.step('Find video for "vibe coding"')
    play.expect('The results page contains a list of videos')

    play.step('Open the third video')
    play.expect('The video page contains a title, description, and comments')
