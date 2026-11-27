"""Code panel sizing: the lines shown and the column width for them (mirrors visibleCode in remotion/src/compositions/NarratedSegment.tsx)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_episode as re_  # noqa: E402


def block(n, indent_from=None):
    return "\n".join(("  x: 1," if indent_from is not None and i >= indent_from else f"top{i}()") for i in range(n))


def test_short_listing_is_shown_whole():
    assert len(re_.visible_code_lines(block(25))) == 25


def test_long_listing_is_cut_at_an_unindented_line():
    code = "\n".join(["{"] + ["  a: 1,"] * 20 + ["}", "next()"] + ["  b: 2,"] * 30)
    shown = re_.visible_code_lines(code)
    assert shown[-1] == "}" and len(shown) <= 25  # the object is closed, not stopped halfway


def test_long_indented_listing_is_cut_at_the_limit():
    assert len(re_.visible_code_lines("\n".join(["  a: 1,"] * 60))) == 25


def test_column_width_grows_with_the_longest_visible_line_and_is_capped():
    assert re_._calc_code_column_width("x" * 400) == re_._MAX_CODE_COL
    assert re_._calc_code_column_width("ab\nabcdefghij") > re_._calc_code_column_width("ab")
    assert re_._calc_code_column_width(None) == 0
