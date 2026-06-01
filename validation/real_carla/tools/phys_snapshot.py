#!/usr/bin/env python3.7
"""Read the PHYSICAL state of the 6 platoon trucks from a running CARLA server (read-only, no tick).

Actor ids are assigned in spawn order. build_truck_platoon() spawns platoon_a lead + 2 followers,
then platoon_b lead + 2 followers, so the id-sorted vehicles map to
platoon_a_truck0..2, platoon_b_truck0..2. Prints JSON: per vehicle x, y, lane_id, road_id, speed.
"""
import json, math, sys
import carla

c = carla.Client("127.0.0.1", 2000); c.set_timeout(30)
w = c.get_world(); m = w.get_map()
vs = sorted(w.get_actors().filter("vehicle.*"), key=lambda a: a.id)
names = ["platoon_a_truck0", "platoon_a_truck1", "platoon_a_truck2", "platoon_b_truck0", "platoon_b_truck1", "platoon_b_truck2"]
out = {"n_vehicles": len(vs), "vehicles": {}}
for name, a in zip(names, vs):
    loc = a.get_location(); v = a.get_velocity()
    wp = m.get_waypoint(loc, project_to_road=True, lane_type=carla.LaneType.Driving)
    out["vehicles"][name] = {"actor_id": a.id, "type": a.type_id, "x": round(loc.x, 2), "y": round(loc.y, 2),
                             "road_id": wp.road_id, "lane_id": wp.lane_id,
                             "speed_kmh": round(3.6 * math.sqrt(v.x ** 2 + v.y ** 2 + v.z ** 2), 1)}
print(json.dumps(out))
