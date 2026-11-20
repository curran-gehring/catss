"""Verse-map logic for the NT Latin pack: Clementine NT verses grouped into
alignment units against the SBLGNT verses of the shipped interlinear pack."""
import pytest

from catss import vulgate_nt as vn


def _tsv(tmp_path, lines):
    p = tmp_path / "vul.tsv"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_parse_nt_keeps_nt_books_dedups_and_maps_ids(tmp_path):
    p = _tsv(tmp_path, [
        "Genesis\tGn\t1\t1\t1\tIn principio creavit Deus",
        "Joannes\tJo\t43\t1\t1\tIn principio erat Verbum",
        "Joannes\tJo\t43\t1\t1\tIn principio erat Verbum",
        "Apocalypsis\tApc\t73\t22\t21\tGratia Domini nostri",
    ])
    vs = vn.parse_nt(p)
    assert [(v.book_id, v.chapter, v.verse) for v in vs] == [(43, 1, 1), (66, 22, 21)]
    assert vs[0].vul_book == "Jo" and vs[0].text == "In principio erat Verbum"


def test_nt_books_cover_all_27_in_canonical_order():
    assert sorted(vn.NT_BOOKS.values()) == list(range(40, 67))
    assert vn.NT_BOOKS["Mt"] == 40 and vn.NT_BOOKS["Apc"] == 66


LAT = [(1, 1), (1, 2), (1, 3), (2, 1), (2, 2)]
GRK = [(1, 1), (1, 2), (2, 1), (2, 2), (2, 3)]


def test_unlisted_verses_with_same_number_are_identity_units():
    units = vn.resolve_units(LAT, GRK, rows=[
        vn.UnitRow(latin="1:3", greek="", home="1:2", note="omitted"),
        vn.UnitRow(latin="2:2", greek="2:2,2:3", home="", note="split"),
    ])
    got = [(u.latin, u.greek, u.status, u.home) for u in units]
    assert got == [
        ([(1, 1)], [(1, 1)], ["same"], [(1, 1)]),
        ([(1, 2)], [(1, 2)], ["same"], [(1, 2)]),
        ([(1, 3)], [], ["latin_only"], [(1, 2)]),
        ([(2, 1)], [(2, 1)], ["same"], [(2, 1)]),
        ([(2, 2)], [(2, 2), (2, 3)], ["unit"], [(2, 2)]),
    ]


def test_one_to_one_under_another_number_is_renumbered():
    units = vn.resolve_units([(1, 1), (1, 2)], [(1, 1), (2, 1)], rows=[
        vn.UnitRow(latin="1:2", greek="2:1", home="", note="seam"),
    ])
    assert units[1].status == ["renumbered"] and units[1].home == [(2, 1)]


def test_many_to_one_homes_default_to_first_greek_verse_unless_given():
    units = vn.resolve_units([(6, 51), (6, 52)], [(6, 51)], rows=[
        vn.UnitRow(latin="6:51,6:52", greek="6:51", home="", note=""),
    ])
    assert units[0].home == [(6, 51), (6, 51)] and units[0].status == ["unit", "unit"]
    units = vn.resolve_units([(13, 12), (13, 13)], [(13, 12), (13, 13), (13, 14)], rows=[
        vn.UnitRow(latin="13:12", greek="13:12,13:13", home="", note=""),
        vn.UnitRow(latin="13:13", greek="13:14", home="", note=""),
    ])
    assert [u.status for u in units] == [["unit"], ["renumbered"]]


def test_ranges_expand_against_each_sides_own_verse_order():
    lat = [(7, 52), (7, 53), (8, 1), (8, 2), (8, 12)]
    grk = [(7, 52), (8, 12)]
    units = vn.resolve_units(lat, grk, rows=[
        vn.UnitRow(latin="7:53-8:2", greek="", home="7:53", note="pericope"),
    ])
    lo = [u for u in units if u.status[0] == "latin_only"]
    assert len(lo) == 1 and lo[0].latin == [(7, 53), (8, 1), (8, 2)]


def test_latin_only_needs_a_home_per_verse_or_one_for_all():
    with pytest.raises(ValueError, match="home"):
        vn.resolve_units([(1, 1), (1, 2)], [(1, 1)], rows=[
            vn.UnitRow(latin="1:2", greek="", home="", note=""),
        ])


@pytest.mark.parametrize("rows,msg", [
    ([vn.UnitRow("1:1", "1:1", "", ""), vn.UnitRow("1:1", "1:2", "", "")], "twice"),
    ([vn.UnitRow("1:1", "1:1,1:2", "", ""), vn.UnitRow("1:2", "1:2", "", "")], "twice"),
    ([vn.UnitRow("9:9", "1:1", "", "")], "unknown"),
    ([vn.UnitRow("1:2", "", "1:1", "")], "Greek verse"),   # Greek 1:2 left over
])
def test_inconsistent_rows_fail_fast(rows, msg):
    with pytest.raises(ValueError, match=msg):
        vn.resolve_units([(1, 1), (1, 2)], [(1, 1), (1, 2)], rows=rows)


def test_leftover_latin_verse_without_greek_counterpart_fails():
    with pytest.raises(ValueError, match="Latin verse"):
        vn.resolve_units([(1, 1), (1, 2)], [(1, 1)], rows=[])


def test_load_unit_rows_reads_book_keyed_tsv(tmp_path):
    p = tmp_path / "u.tsv"
    p.write_text(
        "# book\tlatin\tgreek\thome\tnote\n"
        "43\t6:51,6:52\t6:51\t\tsplit\n"
        "\n"
        "44\t8:37\t\t8:36\tomitted in SBLGNT\n", encoding="utf-8")
    rows = vn.load_unit_rows(p)
    assert rows == {43: [vn.UnitRow("6:51,6:52", "6:51", "", "split")],
                    44: [vn.UnitRow("8:37", "", "8:36", "omitted in SBLGNT")]}


def test_load_unit_rows_rejects_malformed_lines(tmp_path):
    p = tmp_path / "u.tsv"
    p.write_text("43\t6:51\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 1"):
        vn.load_unit_rows(p)


def test_pairwise_row_expands_a_shift_into_renumbered_one_to_one_units():
    lat = [(8, 39), (9, 1), (9, 2)]
    grk = [(9, 1), (9, 2), (9, 3)]
    units = vn.resolve_units(lat, grk, rows=[
        vn.UnitRow(latin="8:39", greek="9:1", home="", note="seam"),
        vn.UnitRow(latin="9:1-2", greek="9:2-3", home="pairwise", note="Mark 9 runs one ahead"),
    ])
    assert [(u.latin, u.greek, u.status) for u in units] == [
        ([(8, 39)], [(9, 1)], ["renumbered"]),
        ([(9, 1)], [(9, 2)], ["renumbered"]),
        ([(9, 2)], [(9, 3)], ["renumbered"]),
    ]
    assert units[1].note == "Mark 9 runs one ahead"


def test_pairwise_needs_equal_counts():
    with pytest.raises(ValueError, match="pairwise"):
        vn.resolve_units([(1, 1), (1, 2)], [(1, 1)], rows=[
            vn.UnitRow(latin="1:1-2", greek="1:1", home="pairwise", note=""),
        ])
