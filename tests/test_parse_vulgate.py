"""Parser tests for the Clementine Vulgate TSV, driven by inline fixtures
shaped like raw/vulgate/vul.tsv (name\\tabbrev\\tbook#\\tch\\tverse\\ttext).

The real source and catss.db are gitignored (not redistributed), so every
case here is a hand-built fixture verified against the live data during
development."""
import pathlib

from catss import parse_vulgate


def _row(name, abbrev, bnum, ch, v, text):
    return f"{name}\t{abbrev}\t{bnum}\t{ch}\t{v}\t{text}"


def _parse(tmp_path: pathlib.Path, *rows: str):
    p = tmp_path / "vul.tsv"
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return list(parse_vulgate.parse_file(p))


def _ref(vv):
    return (vv.catss_osis, vv.catss_chapter, vv.catss_verse)


def test_dedup_triplication(tmp_path):
    # Every verse is byte-identical x3 in the source; parse keeps one.
    line = _row("Genesis", "Gn", 1, 1, 1, "In principio creavit Deus.")
    verses = _parse(tmp_path, line, line, line)
    assert len(verses) == 1
    assert _ref(verses[0]) == ("Gen", 1, 1)
    assert verses[0].text == "In principio creavit Deus."
    assert verses[0].pivot == "mt"


def test_conflicting_duplicate_raises(tmp_path):
    # Same ref, DIFFERENT text = corrupt source, not a triplicate. Fail loud.
    import pytest
    a = _row("Genesis", "Gn", 1, 1, 1, "In principio creavit Deus.")
    b = _row("Genesis", "Gn", 1, 1, 1, "WRONG conflicting text.")
    with pytest.raises(ValueError, match="conflicting duplicate"):
        _parse(tmp_path, a, b)


def test_parse_stats_surface_skip_counts(tmp_path):
    p = tmp_path / "vul.tsv"
    p.write_text("\n".join([
        _row("Genesis", "Gn", 1, 1, 1, "In principio."),   # yielded
        _row("Genesis", "Gn", 1, 1, 1, "In principio."),   # duplicate
        _row("Matthaeus", "Mt", 47, 1, 1, "Liber."),       # NT -> unmapped
        "too\tfew\tcols",                                   # malformed
        _row("Genesis", "Gn", 1, "x", "y", "bad ref"),     # malformed
    ]) + "\n", encoding="utf-8")
    stats = {}
    list(parse_vulgate.parse_file(p, stats=stats))
    assert stats == {"malformed": 2, "duplicates": 1,
                     "unmapped": 1, "yielded": 1}


def test_nt_and_unmapped_dropped(tmp_path):
    verses = _parse(
        tmp_path,
        _row("Matthaeus", "Mt", 47, 1, 1, "Liber generationis."),
        _row("Apocalypsis", "Apc", 73, 22, 21, "Gratia Domini."),
        _row("Genesis", "Gn", 1, 1, 1, "In principio."),
    )
    assert [v.vul_book for v in verses] == ["Gn"]


def test_psalms_pivot_is_lxx(tmp_path):
    verses = _parse(tmp_path, _row("Psalmi", "Ps", 21, 23, 1, "Dominus regit me."))
    assert _ref(verses[0]) == ("Ps", 23, 1)
    assert verses[0].pivot == "lxx"


def test_daniel_susanna_and_bel_split(tmp_path):
    verses = _parse(
        tmp_path,
        _row("Daniel", "Dn", 32, 1, 1, "Anno tertio."),       # Daniel proper
        _row("Daniel", "Dn", 32, 13, 1, "Et erat vir."),      # Susanna
        _row("Daniel", "Dn", 32, 14, 1, "Erat autem Daniel."),# Bel (+1 shift)
        _row("Daniel", "Dn", 32, 14, 42, "Tunc rex ait."),    # Bel tail (orphan side)
    )
    refs = {v.vul_verse if v.catss_osis != "Dan" else "dan": _ref(v) for v in verses}
    assert _ref(verses[0]) == ("Dan", 1, 1)
    assert _ref(verses[1]) == ("SusTh", 1, 1)
    # Theodotion v1 is the Astyages prologue the Vulgate omits -> +1.
    assert _ref(verses[2]) == ("BelTh", 1, 2)
    assert _ref(verses[3]) == ("BelTh", 1, 43)
    assert verses[1].pivot == "lxx" and verses[2].pivot == "lxx"


def test_baruch_letter_of_jeremiah_split(tmp_path):
    verses = _parse(
        tmp_path,
        _row("Baruch", "Bar", 30, 5, 9, "Adducet enim Deus."),  # Baruch proper
        _row("Baruch", "Bar", 30, 6, 1, "Exemplar epistolae."), # Letter of Jeremiah
    )
    assert _ref(verses[0]) == ("Bar", 5, 9)
    assert _ref(verses[1]) == ("EpJer", 1, 1)
    assert verses[1].pivot == "lxx"


def test_joel_chapter_division(tmp_path):
    verses = _parse(
        tmp_path,
        _row("Joael", "Joel", 34, 2, 27, "Et scietis."),        # stays 2:27
        _row("Joael", "Joel", 34, 2, 28, "Et erit post haec."), # -> MT 3:1
        _row("Joael", "Joel", 34, 3, 1, "Quia ecce."),          # -> MT 4:1
    )
    assert _ref(verses[0]) == ("Joel", 2, 27)
    assert _ref(verses[1]) == ("Joel", 3, 1)
    assert _ref(verses[2]) == ("Joel", 4, 1)


def test_malachi_chapter_division(tmp_path):
    verses = _parse(
        tmp_path,
        _row("Malachias", "Mal", 44, 3, 18, "Et convertemini."),  # stays 3:18
        _row("Malachias", "Mal", 44, 4, 1, "Ecce enim dies."),    # -> MT 3:19
        _row("Malachias", "Mal", 44, 4, 6, "Ne forte veniam."),   # -> MT 3:24
    )
    assert _ref(verses[0]) == ("Mal", 3, 18)
    assert _ref(verses[1]) == ("Mal", 3, 19)
    assert _ref(verses[2]) == ("Mal", 3, 24)


def test_reigns_and_paralipomenon_mapping(tmp_path):
    verses = _parse(
        tmp_path,
        _row("Regum I", "1Rg", 9, 1, 1, "Fuit vir."),
        _row("Regum III", "3Rg", 11, 1, 1, "Et rex David."),
        _row("Paralipomenon I", "1Par", 13, 1, 1, "Adam, Seth."),
    )
    assert _ref(verses[0]) == ("1Sam", 1, 1)
    assert _ref(verses[1]) == ("1Kgs", 1, 1)
    assert _ref(verses[2]) == ("1Chr", 1, 1)


def test_tokenize_latin_basic():
    toks = parse_vulgate.tokenize_latin("In principio creavit Deus cælum et terram.")
    assert [s for s, _ in toks] == [
        "In", "principio", "creavit", "Deus", "caelum", "et", "terram"]
    assert [n for _, n in toks] == [
        "in", "principio", "creavit", "deus", "caelum", "et", "terram"]


def test_tokenize_latin_drops_bare_punctuation_and_brackets():
    # spaced ':' and the '<...>' superscription brackets must not become tokens
    toks = parse_vulgate.tokenize_latin("Dixitque Deus : <Fiat> lux.")
    assert [s for s, _ in toks] == ["Dixitque", "Deus", "Fiat", "lux"]


def test_tokenize_latin_folds_ligatures_and_accents():
    toks = parse_vulgate.tokenize_latin("prǽ œconomus Æthiopiæ")
    norms = [n for _, n in toks]
    assert norms == ["prae", "oeconomus", "aethiopiae"]


def test_malformed_lines_skipped(tmp_path):
    verses = _parse(
        tmp_path,
        "too\tfew\tcols",
        _row("Genesis", "Gn", 1, "x", "y", "non-integer ref"),
        _row("Genesis", "Gn", 1, 1, 1, "In principio."),
    )
    assert len(verses) == 1
    assert verses[0].text == "In principio."
