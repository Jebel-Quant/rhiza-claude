"""Tests for `scripts/maffay.py`."""

from __future__ import annotations

import json

import maffay
import pytest


def test_catalogue_entries_are_well_formed():
    for entry in maffay.BONMOTS:
        assert set(entry) == {"line", "song", "year", "themes", "apply"}
        assert entry["line"] and entry["song"] and entry["apply"]
        assert 1965 < entry["year"] < 2030
        assert entry["themes"], f"{entry['song']} has no themes, so --theme can never find it"


def test_themes_are_sorted_and_deduplicated():
    result = maffay.themes()
    assert result == sorted(set(result))
    assert "nessaja" in result


def test_candidates_without_theme_returns_everything():
    assert len(maffay.candidates(None)) == len(maffay.BONMOTS)


def test_candidates_matches_theme_keyword_case_insensitively():
    matched = maffay.candidates("NESSAJA")
    assert matched
    assert all("nessaja" in e["themes"] for e in matched)


def test_candidates_matches_song_title_substring():
    matched = maffay.candidates("brücken")
    assert [e["song"] for e in matched] == ["Über sieben Brücken musst du gehn"]


def test_candidates_unknown_theme_is_empty():
    assert maffay.candidates("stairway to heaven") == []


def test_pick_is_seed_reproducible():
    assert maffay.pick(seed=7) == maffay.pick(seed=7)


def test_pick_covers_the_whole_catalogue_across_seeds():
    """Every entry is reachable — a pick that could never return an entry is a bug."""
    songs = {maffay.pick(seed=s)["song"] for s in range(200)}
    assert songs == {e["song"] for e in maffay.BONMOTS}


def test_pick_returns_none_when_theme_matches_nothing():
    assert maffay.pick(theme="polka") is None


def test_render_separates_the_quote_from_our_gloss():
    text = maffay.render(maffay.BONMOTS[0])
    assert "Peter Maffay" in text
    assert "1980" in text
    # The gloss is ours, so it must never look like part of the lyric.
    assert "Für uns:" in text


def test_main_prints_a_bonmot(capsys):
    assert maffay.main(["--seed", "1"]) == maffay.EXIT_OK
    assert "Peter Maffay" in capsys.readouterr().out


def test_main_json_emits_one_object(capsys):
    assert maffay.main(["--seed", "1", "--json"]) == maffay.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["song"] and payload["year"]


def test_main_theme_filter_narrows_the_pool(capsys):
    assert maffay.main(["--theme", "sommer", "--json"]) == maffay.EXIT_OK
    assert json.loads(capsys.readouterr().out)["song"] == "Und es war Sommer"


def test_main_unknown_theme_exits_one_and_lists_themes(capsys):
    assert maffay.main(["--theme", "yodeling"]) == maffay.EXIT_NO_MATCH
    err = capsys.readouterr().err
    assert "no song matches" in err
    assert "nessaja" in err


def test_main_list_prints_every_song(capsys):
    assert maffay.main(["--list"]) == maffay.EXIT_OK
    out = capsys.readouterr().out
    for entry in maffay.BONMOTS:
        assert entry["song"] in out
    assert f"{len(maffay.BONMOTS)} songs" in out


def test_main_list_json_includes_themes_and_entries(capsys):
    assert maffay.main(["--list", "--json"]) == maffay.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["themes"] == maffay.themes()
    assert len(payload["bonmots"]) == len(maffay.BONMOTS)


def test_main_list_respects_the_theme_filter(capsys):
    assert maffay.main(["--list", "--theme", "nessaja", "--json"]) == maffay.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert 0 < len(payload["bonmots"]) < len(maffay.BONMOTS)


def test_module_runs_as_a_script():
    """`python scripts/maffay.py` must work, not just the imported functions."""
    with pytest.raises(SystemExit) as exc:
        maffay.sys.exit(maffay.main(["--seed", "3"]))
    assert exc.value.code == maffay.EXIT_OK
