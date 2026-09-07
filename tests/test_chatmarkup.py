"""What Carmen writes, and what the chat draws.

She answers in plain text with a little Markdown in it, because that is what a
model writes when it is asked for a list of deliverables and their dates. A
table typed as pipes and then drawn as pipes is unreadable — the whole point of
a table is that the columns line up.
"""

from __future__ import annotations

from app.chatmarkup import to_html


def test_a_pipe_table_becomes_a_table():
    made = str(to_html(
        "Here they are.\n"
        "\n"
        "| Trade | Booked | CPI |\n"
        "| --- | ---: | --- |\n"
        "| Marine | 900 | 1.05 |\n"
        "| Geotechnical | 850 | 0.92 |\n"))
    assert "<table>" in made
    assert made.count("<tr>") == 3, "a header row and two lines"
    assert "<th>Trade</th>" in made and "<td>Marine</td>" in made
    assert "|" not in made, "no pipes left on the page"


def test_a_table_scrolls_inside_itself():
    """A wide table must not push the conversation sideways."""
    made = str(to_html("| a | b |\n| - | - |\n| 1 | 2 |"))
    assert "table-scroll" in made


def test_a_short_row_is_padded_rather_than_dropped():
    made = str(to_html("| a | b | c |\n| - | - | - |\n| 1 | 2 |"))
    assert made.count("<td>") == 3


def test_pipes_that_are_not_a_table_stay_as_words():
    made = str(to_html("Use A | B to mean either."))
    assert "<table>" not in made and "A | B" in made


def test_bullets_and_numbers_become_lists():
    made = str(to_html("Two things:\n- one\n- two"))
    assert "<ul" in made and made.count("<li>") == 2
    numbered = str(to_html("1. first\n2. second"))
    assert "<ol" in numbered and numbered.count("<li>") == 2


def test_bold_and_code_are_honoured():
    made = str(to_html("The **critical** path runs through `1.4`."))
    assert "<strong>critical</strong>" in made and "<code>1.4</code>" in made


def test_paragraphs_keep_their_line_breaks():
    made = str(to_html("One line\nand the next\n\nA new paragraph"))
    assert made.count("<p>") == 2 and "<br>" in made


def test_nothing_a_model_writes_can_put_markup_on_the_page():
    """Everything is escaped first and built as tags afterwards — including
    anything quoted in out of a document somebody attached."""
    made = str(to_html("<script>alert(1)</script> and <b>bold</b>"))
    assert "<script>" not in made and "&lt;script&gt;" in made
    assert "<b>bold</b>" not in made

    inside = str(to_html("| Name |\n| - |\n| <img src=x onerror=1> |"))
    assert "<img" not in inside


def test_an_empty_answer_draws_nothing():
    assert str(to_html("")) == ""
    assert str(to_html(None)) == ""
