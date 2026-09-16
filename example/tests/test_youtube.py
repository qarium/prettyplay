from prettyplay import PrettyPlay


def test_youtube_search(play: PrettyPlay):
    play.step("Open https://youtube.com")

    with play.group("Search for videos based on request") as search:
        search.step("Accept all the terms of the agreement")
        search.step('Find videos for "vibe coding"')

        search.expect("The results page contains a list of videos")

    play.step("Open the third video")
    play.expect("The video page contains a title of video")
