from prettyplay import PrettyPlay


def test_youtube_search(play: PrettyPlay):
    vars = {"url": "https://youtube.com"}
    play.step("Open {{ vars.url }}", vars=vars)

    with play.group("Search for videos based on request") as search:
        # consent is already accepted on repeat visits — the step tolerates the dialog's absence
        search.step("Accept the consent dialog if it appears")
        search.step('Find videos for "vibe coding"')

        search.expect("The results page contains a list of videos")

    play.step('Save title of third video in {% var video_title %}')
    play.step("Open the video '{{ video_title }}'")
    # locale-robust on purpose: YouTube localizes the video page title, the shared latin
    # fragment is the only stable text across locales
    play.expect("The video page contains the text 'vibe coding'")
