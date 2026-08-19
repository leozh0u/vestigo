"""Tests for the geographic primitives.

Mostly longitude. Latitude behaves and longitude does not: a band written as
170 to -170 is 20 degrees wide across the dateline, and getting that backwards
silently turns a tight constraint into one that admits almost everything.
"""
import pytest

from vestigo.geo import (
    LatLon,
    haversine,
    lat_band_excess,
    lon_band_excess,
    lon_band_width,
    norm_lon,
)


def test_longitude_is_folded_on_construction():
    assert LatLon(0.0, 190.0).lon == pytest.approx(-170.0)
    assert LatLon(0.0, 350.0).lon == pytest.approx(-10.0)


def test_out_of_range_latitude_is_rejected():
    with pytest.raises(ValueError):
        LatLon(91.0, 0.0)


def test_norm_lon():
    assert norm_lon(180.0) == pytest.approx(-180.0)
    assert norm_lon(-180.0) == pytest.approx(-180.0)
    assert norm_lon(0.0) == 0.0


def test_haversine_against_a_known_pair():
    # The Mexico and Nairobi points from the arm A2 continent flip. The
    # write-up puts that image's run-to-run noise at 14,951 km.
    d = haversine(LatLon(20.450895, -100.467564), LatLon(-1.286389, 36.817223))
    assert 14800 < d < 15100


def test_a_point_is_zero_from_itself():
    p = LatLon(14.836242, 100.249282)
    assert haversine(p, p) == pytest.approx(0.0, abs=1e-9)


def test_lat_band_excess():
    assert lat_band_excess(17.0, 15.0, 20.0) == 0.0
    assert lat_band_excess(15.0, 15.0, 20.0) == 0.0       # edges are inside
    assert lat_band_excess(10.0, 15.0, 20.0) == pytest.approx(5.0)
    assert lat_band_excess(25.0, 15.0, 20.0) == pytest.approx(5.0)


def test_a_band_written_backwards_still_works():
    assert lat_band_excess(17.0, 20.0, 15.0) == 0.0


def test_lon_band_width_goes_east():
    assert lon_band_width(-115.0, -85.0) == pytest.approx(30.0)
    assert lon_band_width(170.0, -170.0) == pytest.approx(20.0)
    assert lon_band_width(-170.0, 170.0) == pytest.approx(340.0)


def test_lon_band_excess_across_the_dateline():
    assert lon_band_excess(175.0, 170.0, -170.0) == 0.0
    assert lon_band_excess(-175.0, 170.0, -170.0) == 0.0
    assert lon_band_excess(165.0, 170.0, -170.0) == pytest.approx(5.0)
    assert lon_band_excess(-165.0, 170.0, -170.0) == pytest.approx(5.0)


def test_lon_band_excess_measures_to_the_nearer_edge():
    assert lon_band_excess(-120.0, -115.0, -85.0) == pytest.approx(5.0)
    assert lon_band_excess(-80.0, -115.0, -85.0) == pytest.approx(5.0)
    # Halfway round the world from a narrow band, either edge is far.
    assert lon_band_excess(80.0, -115.0, -85.0) > 160.0
