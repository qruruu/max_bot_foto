"""Photo evidence on an approved network. Never connect territories or invent shortcuts."""
import heapq
import math
from collections import defaultdict

from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import substring, transform, unary_union
from shapely.strtree import STRtree


class RouteNetwork:
    def __init__(self, territory, paths, buildings):
        self.territory = territory
        lon, lat = territory.centroid.coords[0]
        self.origin = lon, lat
        self.scale = 111195 * math.cos(math.radians(lat)), 111195
        self.area = self.project(territory)
        self.obstacles = unary_union([self.project(shape(p)) for p in buildings])
        lines = []
        for path in paths:
            line = self.project(LineString(path))
            if not line.is_simple or line.length < .1:
                raise ValueError("Маршрут содержит петлю или слишком короткий участок")
            if not self.area.covers(line):
                raise ValueError("Маршрут должен целиком находиться внутри одной территории")
            if line.intersects(self.obstacles):
                raise ValueError("Маршрут пересекает здание. Обведите его по дороге или проходу")
            lines.append(line)
        # Node crossings and remove duplicate/overlapping lengths before measuring coverage.
        merged = unary_union(lines)
        self.lines = self.parts(merged)
        if len(self.lines) > 10000:
            raise ValueError("Слишком сложный маршрут: разделите его на меньшие территории")
        self.total = sum(line.length for line in self.lines)
        self.tree = STRtree(self.lines) if self.lines else None

    def project(self, geometry, reverse=False):
        ox, oy = self.origin
        sx, sy = self.scale
        if reverse:
            return transform(lambda x, y, z=None: (x / sx + ox, y / sy + oy), geometry)
        return transform(lambda x, y, z=None: ((x - ox) * sx, (y - oy) * sy), geometry)

    @staticmethod
    def parts(geometry):
        if geometry.is_empty:
            return []
        if geometry.geom_type == "LineString":
            return [geometry]
        return [part for g in getattr(geometry, "geoms", []) for part in RouteNetwork.parts(g)]

    def geojson(self, geometry):
        return mapping(self.project(geometry, reverse=True))

    def coverage(self, photos, snap_m=25, max_gap_minutes=45):
        snaps, cuts = {}, defaultdict(list)
        diagnostics = defaultdict(int)
        for photo in photos:
            if photo["longitude"] is None or photo["latitude"] is None:
                diagnostics["no_coordinates"] += 1
                continue
            point = Point(photo["longitude"], photo["latitude"])
            if not self.territory.covers(point):
                diagnostics["outside"] += 1
                continue
            point = self.project(point)
            if self.obstacles.covers(point):
                diagnostics["inside_building"] += 1
                continue
            if self.tree is None:
                continue
            index = int(self.tree.nearest(point))
            line = self.lines[index]
            distance = line.project(point)
            snapped = line.interpolate(distance)
            # The snap connector must itself stay inside the territory and outside buildings.
            connector = LineString([point, snapped])
            if (point.distance(snapped) > snap_m or not self.area.covers(connector)
                    or connector.intersects(self.obstacles)):
                diagnostics["off_route"] += 1
                continue
            if not photo.get("taken_at") or not photo.get("time_known", True) or photo.get("sender_id") is None:
                diagnostics["unknown_time_or_sender"] += 1
                continue
            snaps[photo["id"]] = index, distance
            cuts[index].append(distance)

        def node(point):
            return tuple(round(v, 6) for v in point)

        graph, edges = defaultdict(list), []
        for i, line in enumerate(self.lines):
            values = sorted(set([0, line.length, *cuts[i]]))
            for a, b in zip(values, values[1:], strict=False):
                if b - a < 1e-7:
                    continue
                segment = substring(line, a, b)
                start, end = node(segment.coords[0]), node(segment.coords[-1])
                eid = len(edges)
                edges.append(segment)
                graph[start].append((end, segment.length, eid))
                graph[end].append((start, segment.length, eid))

        def shortest(start, target):
            queue, best, parent = [(0, start)], {start: 0}, {}
            while queue:
                distance, current = heapq.heappop(queue)
                if distance != best[current]:
                    continue
                if current == target:
                    result = []
                    while current != start:
                        previous, eid = parent[current]
                        result.append(eid)
                        current = previous
                    return result
                for other, weight, eid in graph[current]:
                    candidate = distance + weight
                    if candidate < best.get(other, math.inf):
                        best[other] = candidate
                        parent[other] = current, eid
                        heapq.heappush(queue, (candidate, other))
            return None

        # Keep rejected/outside observations in each timeline: they break the trajectory.
        groups = defaultdict(list)
        for photo in photos:
            if photo.get("taken_at"):
                groups[(photo["chat_id"], photo.get("sender_id"), photo["taken_at"].date())].append(photo)
        covered = set()
        connections = []
        for group in groups.values():
            if any(not photo.get("time_known", True) for photo in group):
                diagnostics["uncertain_order"] += 1
                continue
            group.sort(key=lambda p: (p["taken_at"], p["id"]))
            for left, right in zip(group, group[1:], strict=False):
                if left["id"] not in snaps or right["id"] not in snaps:
                    continue
                gap = (right["taken_at"] - left["taken_at"]).total_seconds()
                if not 0 < gap <= max_gap_minutes * 60:
                    diagnostics["time_gap"] += 1
                    continue
                a, da = snaps[left["id"]]
                b, db = snaps[right["id"]]
                path = shortest(node(self.lines[a].interpolate(da).coords[0]),
                                node(self.lines[b].interpolate(db).coords[0]))
                if path is None:
                    diagnostics["disconnected"] += 1
                    continue
                covered.update(path)
                connections.append({"from_photo": left["id"], "to_photo": right["id"],
                                    "geometry": self.geojson(unary_union([edges[e] for e in path]))})
        done = sum(edges[e].length for e in covered)
        return {
            "total_m": round(self.total, 1), "covered_m": round(done, 1),
            "remaining_m": round(max(0, self.total - done), 1),
            "remaining_percent": round(100 * max(0, self.total - done) / self.total, 1) if self.total else None,
            "covered": self.geojson(unary_union([edges[e] for e in covered])),
            "remaining": self.geojson(unary_union([edge for e, edge in enumerate(edges) if e not in covered])),
            "connections": connections, "diagnostics": dict(diagnostics), "matched_photos": len(snaps),
        }
