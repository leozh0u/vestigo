"""Tests for agreement across samples.

Every image is already run three times. Until now the samples reported how much
the answer wobbled and the answer itself came from one of them, arbitrarily.
One image in the eighth eval run returned answers 10,387 km apart and each was
stated with a confidence.

The property under test throughout: **agreement narrows and never widens.**
Samples share an image, a model and a prompt, so they are correlated, and
agreement between correlated draws is weak evidence. Disagreement is not:
one draw landing elsewhere proves the evidence did not determine the answer.
"""
from types import SimpleNamespace as NS

import pytest

from vestigo.board import Level
from vestigo.consensus import Consensus, consense
from vestigo.geo import LatLon


def run(lat, lon, level=Level.CITY, value="Somewhere", conf=0.6):
    answer = NS(level=level, value=value, id="c1")
    return NS(best_point=LatLon(lat, lon), answer=answer,
              resolution=NS(confidences={"c1": conf}))


def declined():
    return NS(best_point=None, answer=None, resolution=NS(confidences={}))


# --------------------------------------------------------------------------
# Agreement
# --------------------------------------------------------------------------

def test_samples_that_agree_closely_keep_their_level():
    c = consense([run(-41.5, -72.9), run(-41.51, -72.91), run(-41.49, -72.88)])
    assert c.level is Level.CITY
    assert c.unanimous
    assert c.demoted_from is None


def test_a_majority_carries_and_the_outlier_is_dropped():
    c = consense([run(-41.5, -72.9), run(-41.6, -72.8), run(51.5, -0.1, value="London")])
    assert c.level is Level.CITY
    assert c.value != "London"
    assert c.agreement == pytest.approx(2 / 3)


def test_samples_that_agree_on_nothing_support_no_answer():
    """Three answers a hemisphere apart. Any one of them stated alone would
    carry a confidence, and this is the case that catches."""
    c = consense([run(-41.5, -72.9), run(51.5, -0.1), run(35.7, 139.7)])
    assert c.level is None
    assert c.point is None
    assert c.spread_km > 10_000


def test_spread_is_the_widest_gap_not_the_average():
    """An average hides exactly the case worth catching: two samples close
    together and a third on another continent averages to something calm."""
    c = consense([run(0.0, 0.0), run(0.01, 0.01), run(0.0, 120.0)])
    assert c.spread_km > 13_000


# --------------------------------------------------------------------------
# It narrows and never widens
# --------------------------------------------------------------------------

def test_close_agreement_does_not_buy_a_finer_level_than_was_claimed():
    """Three samples within a few hundred metres, all saying 'Chile'. They
    support Chile. Correlated draws agreeing is not evidence of precision."""
    c = consense([run(-41.5, -72.9, Level.COUNTRY, "Chile"),
                  run(-41.51, -72.91, Level.COUNTRY, "Chile"),
                  run(-41.49, -72.88, Level.COUNTRY, "Chile")])
    assert c.level is Level.COUNTRY
    assert c.demoted_from is None


def test_scattered_point_claims_are_demoted_to_where_they_actually_agree():
    """Three confident point claims spread over tens of kilometres. Each was
    stated as a point; together they support a region."""
    c = consense([run(-41.5, -72.9, Level.POINT, "a house"),
                  run(-42.3, -72.4, Level.POINT, "a barn"),
                  run(-41.9, -72.6, Level.POINT, "a shed")])
    assert c.level is Level.REGION
    assert c.demoted_from is Level.POINT
    assert "demoted" in c.describe()


def test_the_reported_point_is_one_a_sample_proposed():
    """The medoid, not the mean. An average of two points on opposite sides of
    the world is an ocean neither sample named."""
    runs = [run(10.0, 10.0), run(10.1, 10.1), run(10.2, 10.2)]
    c = consense(runs)
    assert any(c.point.lat == r.best_point.lat and c.point.lon == r.best_point.lon
               for r in runs)


def test_the_centre_is_the_sample_the_others_gathered_around():
    """Not the most confident one. Otherwise a single loud sample names a place
    the group never agreed on."""
    c = consense([run(0.0, 0.0, value="edge", conf=0.99),
                  run(0.1, 0.1, value="middle", conf=0.1),
                  run(0.2, 0.2, value="other edge", conf=0.1)])
    assert c.value == "middle"


# --------------------------------------------------------------------------
# Degenerate cases
# --------------------------------------------------------------------------

def test_no_sample_answering_is_itself_an_answer():
    c = consense([declined(), declined()])
    assert c.level is None
    assert c.n_answered == 0
    assert "no sample" in c.note


def test_one_answer_stands_but_says_it_was_unchecked():
    c = consense([run(0.0, 0.0), declined(), declined()])
    assert c.level is Level.CITY
    assert c.n_answered == 1
    assert c.n_total == 3
    assert "nothing to check it against" in c.note


def test_declining_samples_do_not_dilute_the_agreement():
    """A sample that refused to answer did not disagree. Counting it against
    the majority would punish the system for its own honesty."""
    c = consense([run(0.0, 0.0), run(0.01, 0.01), declined()])
    assert c.agreement == 1.0
    assert c.n_answered == 2
    assert c.n_total == 3


def test_a_two_sample_split_reaches_no_majority_at_that_level():
    """Two samples, one each way. Neither is a majority, so it coarsens until
    they fall in the same bucket."""
    c = consense([run(0.0, 0.0, Level.CITY), run(0.0, 3.0, Level.CITY)])
    assert c.level is not Level.CITY


def test_the_summary_round_trips_to_json():
    c = consense([run(-41.5, -72.9), run(-41.51, -72.91)])
    d = c.to_dict()
    assert d["level"] == "city"
    assert d["n_answered"] == 2
    assert isinstance(d["spread_km"], float)


def test_one_sample_cannot_promote_the_group_to_its_own_granularity():
    """Two samples say "Chile", one names a street, and all three points sit
    inside two hundred metres. Returning a point would be one sample's
    granularity carried by the agreement of two that never asked for it, and
    the medoid's own words would then be reported at a level they do not
    describe: "Chile", labelled as a street address."""
    c = consense([run(-33.450, -70.670, Level.COUNTRY, "Chile"),
                  run(-33.451, -70.671, Level.COUNTRY, "Chile"),
                  run(-33.452, -70.672, Level.POINT, "123 Main St")])
    assert c.level is Level.COUNTRY
    assert c.value == "Chile"


def test_a_majority_claiming_a_fine_level_does_keep_it():
    """The rule is majority, not unanimity. Two point claims and one country
    claim, all in agreement about where, support a point."""
    c = consense([run(-33.450, -70.670, Level.POINT, "a house"),
                  run(-33.451, -70.671, Level.POINT, "a house"),
                  run(-33.452, -70.672, Level.COUNTRY, "Chile")])
    assert c.level is Level.POINT


def test_no_sample_answering_is_distinguishable_from_samples_disagreeing():
    """Both come back with level None, and a report that prints one headline
    over both credits consensus with refusals it had no part in. The counts
    have to tell them apart."""
    silent = consense([declined(), declined(), declined()])
    split = consense([run(-33.4, -70.6), run(51.5, -0.1), run(35.7, 139.7)])
    assert silent.level is None and split.level is None
    assert silent.n_answered == 0
    assert split.n_answered == 3
    assert silent.spread_km == 0.0 and split.spread_km > 10_000
