from datetime import datetime, timedelta

import pytest
from shapely.geometry import Polygon, box, shape

from app.photo_route_geometry import RouteNetwork


def observation(i, x, y=0, **kwargs):
    return {"id": i, "longitude": x, "latitude": y, "chat_id": 1, "sender_id": 1,
            "taken_at": datetime(2026, 11, 2, 10) + timedelta(minutes=i), **kwargs}


def network(paths=None, buildings=None):
    return RouteNetwork(box(-.01, -.01, .01, .01), paths or [[(0, 0), (.001, 0)]], buildings or [])


def test_partial_route_unique_length_and_repeated_passes():
    result = network().coverage([observation(1, 0), observation(2, .0005), observation(3, 0)])
    assert result["remaining_percent"] == 50
    assert result["covered_m"] == pytest.approx(55.6, abs=.1)
    assert result["covered_m"] + result["remaining_m"] == pytest.approx(result["total_m"], abs=.1)


def test_network_bends_around_building_instead_of_shortcut():
    building = box(.0003, -.0001, .0007, .0003)
    net = network([[(0, 0), (0, .0005), (.001, .0005), (.001, 0)]], [building.__geo_interface__])
    result = net.coverage([observation(1, 0), observation(2, .001)])
    assert result["remaining_percent"] == 0
    assert not shape(result["covered"]).intersects(building)


def test_reject_building_intersection_and_territory_shortcut():
    with pytest.raises(ValueError, match="здание"):
        network(buildings=[box(.0004, -.001, .0006, .001).__geo_interface__])
    # Both endpoints inside; connecting them would leave this concave territory.
    territory = Polygon([(0, 0), (.003, 0), (.003, .003), (.002, .003),
                         (.002, .001), (.001, .001), (.001, .003), (0, .003)])
    with pytest.raises(ValueError, match="внутри"):
        RouteNetwork(territory, [[(.0005, .002), (.0025, .002)]], [])


@pytest.mark.parametrize("change", [
    {"chat_id": 2}, {"sender_id": 2}, {"sender_id": None},
    {"taken_at": datetime(2026, 11, 3, 10)}, {"taken_at": datetime(2026, 11, 2, 12)},
])
def test_do_not_connect_people_chats_days_or_time_gaps(change):
    result = network().coverage([observation(1, 0), observation(2, .001, **change)])
    assert result["remaining_percent"] == 100


def test_outside_or_unmatched_photo_interrupts_timeline():
    for x, y in [(.02, 0), (.0005, .005), (None, None)]:
        result = network().coverage([observation(1, 0), observation(2, x, y), observation(3, .001)])
        assert result["remaining_percent"] == 100


def test_disconnected_components_and_no_cross_building_snap():
    net = network([[(-.001, 0), (0, 0)], [(.001, 0), (.002, 0)]])
    assert net.coverage([observation(1, 0), observation(2, .001)])["remaining_percent"] == 100
    # Photo close to the route, but a building is between it and the route.
    net = network(buildings=[box(.0003, .00005, .0007, .0001).__geo_interface__])
    result = net.coverage([observation(1, 0), observation(2, .0005, .00015)])
    assert result["remaining_percent"] == 100


def test_crossings_are_noded_and_overlap_not_double_counted():
    net = network([[(-.001, 0), (.001, 0)], [(0, -.001), (0, .001)], [(0, 0), (.001, 0)]])
    result = net.coverage([observation(1, -.001), observation(2, 0, .001)])
    assert result["remaining_percent"] == 50
