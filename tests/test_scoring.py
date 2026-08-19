"""Tests for granularity-aware scoring and calibration.

The case that matters most is the Bengaluru image, because it is the one that
made the case for this module. Same photograph, same 502 km error, and whether
it counts as a success depends entirely on what the model claimed. Distance
alone cannot see that, and a system optimised against distance alone learns to
stop hedging.
"""
import pytest

from vestigo.board import Level
from vestigo.geo import LatLon
from vestigo.scoring import (
    LEVEL_RADIUS_KM,
    Scored,
    achieved_level,
    calibration_curve,
    expected_calibration_error,
    hit_at_level,
    overshoot,
    parse_level,
    report,
    score,
    spread_km,
    summarise_repeats,
    worst_overshoot,
)

QUERETARO = LatLon(20.450895, -100.467564)
NAIROBI = LatLon(-1.286389, 36.817223)


# -- the case this module exists for ---------------------------------------

def test_the_bengaluru_image_is_a_success_as_a_country_claim():
    """It answered at country granularity, said so, and India was correct."""
    row = Scored("bengaluru", Level.COUNTRY, 502.0, "medium")
    assert row.hit
    assert not row.overclaimed


def test_the_same_error_is_a_failure_as_a_street_claim():
    row = Scored("bengaluru", Level.DISTRICT, 502.0, "medium")
    assert not row.hit
    assert row.overclaimed
    assert row.levels_overclaimed == 3


def test_answering_coarser_than_earned_is_not_a_failure():
    """Stopping at country when the evidence would have supported a city is the
    design working, not a miss. A metric that punished it would push the system
    back towards confident precision."""
    row = Scored("x", Level.COUNTRY, 2.6, "high")
    assert row.hit
    assert row.underclaimed
    assert not row.overclaimed
    assert row.achieved is Level.DISTRICT


# -- the levels ------------------------------------------------------------

def test_the_radii_are_the_im2gps_bands():
    assert LEVEL_RADIUS_KM[Level.CITY] == 25.0
    assert LEVEL_RADIUS_KM[Level.COUNTRY] == 750.0
    assert LEVEL_RADIUS_KM[Level.POINT] == 1.0


def test_radii_get_tighter_as_the_claim_gets_finer():
    levels = sorted(LEVEL_RADIUS_KM)
    radii = [LEVEL_RADIUS_KM[lv] for lv in levels]
    assert radii == sorted(radii, reverse=True)


def test_achieved_level_picks_the_finest_that_holds():
    assert achieved_level(0.5) is Level.POINT
    assert achieved_level(3.0) is Level.DISTRICT
    assert achieved_level(20.0) is Level.CITY
    assert achieved_level(500.0) is Level.COUNTRY
    assert achieved_level(2000.0) is Level.CONTINENT


def test_a_guess_on_the_wrong_side_of_the_planet_achieves_nothing():
    assert achieved_level(14970.0) is None
    row = Scored("kenya flip", Level.COUNTRY, 14970.0, "medium")
    assert row.overclaimed
    assert not row.underclaimed
    assert row.levels_overclaimed == int(Level.COUNTRY)


def test_the_boundary_is_inclusive():
    assert hit_at_level(Level.CITY, 25.0)
    assert not hit_at_level(Level.CITY, 25.001)


def test_the_baseline_granularity_words_all_map():
    assert parse_level("street") is Level.DISTRICT
    assert parse_level("city") is Level.CITY
    assert parse_level("region") is Level.REGION
    assert parse_level("country") is Level.COUNTRY
    assert parse_level(Level.POINT) is Level.POINT


def test_an_unknown_granularity_is_an_error_rather_than_a_default():
    with pytest.raises(ValueError):
        parse_level("roughly thereabouts")


def test_score_computes_the_distance_itself():
    row = score("t", "country", NAIROBI, QUERETARO, confidence="medium")
    assert row.error_km > 14000
    assert row.claimed is Level.COUNTRY
    assert row.overclaimed


# -- overshoot -------------------------------------------------------------

def test_overshoot_is_measured_against_the_claim_not_the_median():
    """A 30 km worst case is excellent for a country claim and terrible for a
    street one. The first version of this metric was worst over median, which
    ranked the best band as the most erratic purely because its median was
    small."""
    assert overshoot(Scored("a", Level.COUNTRY, 30.0)) == pytest.approx(0.04)
    assert overshoot(Scored("b", Level.DISTRICT, 30.0)) == pytest.approx(6.0)


def test_a_band_that_kept_its_promise_scores_at_or_below_one():
    rows = [Scored("a", Level.COUNTRY, 300.0), Scored("b", Level.CITY, 20.0)]
    assert worst_overshoot(rows) <= 1.0


def test_worst_overshoot_finds_the_broken_promise():
    rows = [Scored("a", Level.COUNTRY, 300.0), Scored("b", Level.CITY, 1545.0)]
    assert worst_overshoot(rows) == pytest.approx(61.8)


# -- calibration -----------------------------------------------------------

def test_calibration_reports_hit_rate_at_the_claimed_level():
    rows = [
        Scored("a", Level.CITY, 2.0, "high"),
        Scored("b", Level.CITY, 5.0, "high"),
        Scored("c", Level.CITY, 900.0, "high"),
        Scored("d", Level.COUNTRY, 400.0, "low"),
    ]
    bins = {b.label: b for b in calibration_curve(rows)}
    assert bins["high"].observed == pytest.approx(2 / 3)
    assert bins["low"].observed == 1.0


def test_bands_come_back_strongest_first():
    rows = [Scored("a", Level.CITY, 1.0, "low"),
            Scored("b", Level.CITY, 1.0, "high"),
            Scored("c", Level.CITY, 1.0, "medium")]
    assert [b.label for b in calibration_curve(rows)] == ["high", "medium", "low"]


def test_a_positive_gap_means_overconfident():
    rows = [Scored(f"x{i}", Level.CITY, 900.0, "high") for i in range(4)]
    bins = calibration_curve(rows)
    assert bins[0].observed == 0.0
    assert bins[0].gap > 0            # promised 0.9, delivered 0.0
    assert expected_calibration_error(bins) == pytest.approx(0.9)


def test_a_negative_gap_means_underconfident():
    """What the real data shows once granularity is scored rather than
    distance: the model's low confidence answers are still correct at the
    coarse level they claim."""
    rows = [Scored(f"x{i}", Level.COUNTRY, 300.0, "low") for i in range(4)]
    bins = calibration_curve(rows)
    assert bins[0].observed == 1.0
    assert bins[0].gap < 0


def test_answers_with_no_stated_confidence_are_left_out_of_the_curve():
    rows = [Scored("a", Level.CITY, 1.0, "high"), Scored("b", Level.CITY, 1.0, None)]
    assert sum(b.n for b in calibration_curve(rows)) == 1


def test_report_pulls_it_together():
    rows = [
        Scored("a", Level.COUNTRY, 502.0, "medium"),   # hit, and exactly right
        Scored("b", Level.DISTRICT, 502.0, "medium"),  # overclaimed by three
    ]
    rep = report(rows)
    assert rep.n == 2
    assert rep.hit_rate == 0.5
    assert rep.overclaim_rate == 0.5
    assert rep.median_error_km == 502.0
    # 502 km is a country-level result, so a country claim is neither over nor
    # under. Claiming the level you earned is the only case that is neither.
    assert rep.underclaim_rate == 0.0


def test_a_claim_at_exactly_the_level_earned_is_neither_over_nor_under():
    row = Scored("a", Level.COUNTRY, 502.0, "medium")
    assert row.achieved is Level.COUNTRY
    assert row.hit and not row.overclaimed and not row.underclaimed


def test_underclaiming_shows_up_in_the_report():
    rows = [Scored("a", Level.COUNTRY, 2.6, "high"),
            Scored("b", Level.COUNTRY, 0.4, "high")]
    rep = report(rows)
    assert rep.hit_rate == 1.0
    assert rep.underclaim_rate == 1.0
    assert rep.overclaim_rate == 0.0


def test_reporting_on_nothing_is_an_error():
    with pytest.raises(ValueError):
        report([])


# -- variance --------------------------------------------------------------

def test_spread_is_the_distance_between_the_two_furthest_points():
    assert spread_km([QUERETARO]) == 0.0
    assert spread_km([]) == 0.0
    assert spread_km([QUERETARO, NAIROBI]) > 14000


def test_a_third_point_in_between_does_not_change_the_spread():
    pair = spread_km([QUERETARO, NAIROBI])
    middle = LatLon(10.0, -30.0)
    assert spread_km([QUERETARO, middle, NAIROBI]) == pytest.approx(pair)


def test_summarise_repeats_folds_runs_into_one_row():
    runs = [Scored("t", Level.COUNTRY, 25.0), Scored("t", Level.COUNTRY, 45.0),
            Scored("t", Level.COUNTRY, 14970.0)]
    points = [QUERETARO, LatLon(20.6, -100.2), NAIROBI]
    s = summarise_repeats("t", runs, points)
    assert s.n == 3
    assert s.median_error_km == 45.0
    assert s.best_error_km == 25.0
    assert s.worst_error_km == 14970.0
    assert s.spread_km > 14000
    assert s.hit_rate == pytest.approx(2 / 3)


def test_the_mexico_image_is_marked_unstable():
    """Two identical runs put it 14,951 km apart, so the three together cannot
    be read as one answer whatever their median says."""
    runs = [Scored("t", Level.REGION, 25.0), Scored("t", Level.REGION, 45.0),
            Scored("t", Level.REGION, 14970.0)]
    s = summarise_repeats("t", runs, [QUERETARO, LatLon(20.6, -100.2), NAIROBI])
    assert not s.stable


def test_runs_that_agree_are_marked_stable():
    runs = [Scored("t", Level.COUNTRY, 109.0), Scored("t", Level.COUNTRY, 113.0),
            Scored("t", Level.COUNTRY, 118.0)]
    points = [LatLon(52.8, 20.4), LatLon(52.9, 20.5), LatLon(52.7, 20.3)]
    s = summarise_repeats("t", runs, points)
    assert s.stable


def test_summarising_nothing_is_an_error():
    with pytest.raises(ValueError):
        summarise_repeats("t", [], [])
