from prettyplay import PrettyPlay


def test_youtube_search(play: PrettyPlay):
    play.step('Open https://youtube.com')
    play.step('Accept all the terms of the agreement')

    play.step('Find video for "vibe coding"')
    play.expect('The results page contains a list of videos')

    play.step('Open the third video')
    play.expect('The video page contains a title of video')
