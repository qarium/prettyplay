from prettyplay import PrettyPlay


def test_youtube_search(play: PrettyPlay):
    vars = {"url": "https://youtube.com"}
    play.step("Open {{ vars.url }}", vars=vars)

    with play.group("Search for videos based on request") as search:
        search.step("Accept all the terms of the agreement")
        search.step('Find videos for "vibe coding"')

        search.expect("The results page contains a list of videos")

    play.step('Save title of third video in {% var video_title %}')
    play.step("Open the video '{{ video_title }}'")
    play.expect("The video page contains a title '{{ video_title }}'")
