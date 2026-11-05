#!/usr/bin/env python3
"""Headless physical reproduction experiment, using a real CARLA server."""
import argparse
import json
import math
import os
from pathlib import Path
import queue
import signal
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.request import Request, urlopen

import carla
from executor import TransferExecutor


def drive_case(client, output, protected):
    name = 'fixed' if protected else 'vulnerable'
    folder = output / name
    folder.mkdir(parents=True, exist_ok=True)
    world = client.load_world('Town06')
    original = world.get_settings()
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 0.05
    settings.no_rendering_mode = False  # Offscreen rendering is needed for RGB.
    world.apply_settings(settings)
    world.set_weather(carla.WeatherParameters.ClearNoon)
    actors, collisions, frames, events, telemetry = [], [], queue.Queue(), [], []
    executor = TransferExecutor(deduplicate=protected)
    server = None
    try:
        library = world.get_blueprint_library()
        candidates = list(library.filter('vehicle.carlamotors.european_hgv'))
        if not candidates:
            candidates = list(library.filter('vehicle.carlamotors.carlacola'))
        if not candidates:
            raise RuntimeError('CARLA installation has no supported truck blueprint')
        bp = candidates[0]
        bp.set_attribute('role_name', 'duplicate_commit_experiment')
        ego = obstacle = None
        for transform in world.get_map().get_spawn_points():
            wp = world.get_map().get_waypoint(transform.location)
            ahead = wp.next(28.0)
            if wp.is_junction or not ahead or ahead[0].is_junction:
                continue
            other = ahead[0].transform
            yaw_delta = (other.rotation.yaw - transform.rotation.yaw + 180) % 360 - 180
            if abs(yaw_delta) > 2 or abs(transform.rotation.pitch) > 1:
                continue
            ego = world.try_spawn_actor(bp, carla.Transform(
                transform.location + carla.Location(z=0.5), transform.rotation))
            if ego is None:
                continue
            obstacle = world.try_spawn_actor(bp, carla.Transform(
                other.location + carla.Location(z=0.5), other.rotation))
            if obstacle is not None:
                actors.extend([ego, obstacle])
                break
            ego.destroy()
            ego = None
        if ego is None or obstacle is None:
            raise RuntimeError('No free straight road spawn pair')
        obstacle.apply_control(carla.VehicleControl(brake=1, hand_brake=True))
        sensor_bp = world.get_blueprint_library().find('sensor.other.collision')
        sensor = world.spawn_actor(sensor_bp, carla.Transform(), attach_to=ego)
        actors.append(sensor)
        sensor.listen(lambda event: collisions.append({
            'frame': event.frame, 'other_actor_id': event.other_actor.id,
            'other_actor_type': event.other_actor.type_id,
            'impulse': math.sqrt(event.normal_impulse.x ** 2 +
                                 event.normal_impulse.y ** 2 + event.normal_impulse.z ** 2)}))
        # Actor transforms in synchronous mode are populated after the first tick.
        world.tick()
        camera_bp = world.get_blueprint_library().find('sensor.camera.rgb')
        camera_bp.set_attribute('image_size_x', '1280')
        camera_bp.set_attribute('image_size_y', '720')
        camera_bp.set_attribute('fov', '90')
        camera_bp.set_attribute('sensor_tick', '0.05')
        start = ego.get_transform()
        yaw = math.radians(start.rotation.yaw)
        camera_transform = carla.Location(
            x=start.location.x + 10 * math.cos(yaw) + 15 * math.sin(yaw),
            y=start.location.y + 10 * math.sin(yaw) - 15 * math.cos(yaw),
            z=start.location.z + 23)
        aim = (ego.get_location() + obstacle.get_location()) * 0.5
        direction = aim - camera_transform
        camera = world.spawn_actor(camera_bp, carla.Transform(camera_transform,
            carla.Rotation(pitch=math.degrees(math.atan2(direction.z,
                math.hypot(direction.x, direction.y))),
                yaw=math.degrees(math.atan2(direction.y, direction.x)))))
        actors.append(camera)
        camera.listen(frames.put)

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                started = executor.commit(body['request_id'])
                events.append({'event': 'commit', 'frame': world.get_snapshot().frame,
                               'request_id': body['request_id'], 'started': started,
                               'starts': executor.starts, 'braking': executor.braking})
                payload = json.dumps({'started': started, 'starts': executor.starts}).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        server = HTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()

        def commit():
            request = Request('http://127.0.0.1:%s/commit' % server.server_port,
                              data=b'{"request_id":"transfer-001"}',
                              headers={'Content-Type': 'application/json'})
            with urlopen(request, timeout=3) as response:
                return json.load(response)

        last_image = None

        def tick(label):
            nonlocal last_image
            throttle, brake = executor.control()
            ego.apply_control(carla.VehicleControl(throttle=throttle, brake=brake))
            frame = world.tick()
            velocity = ego.get_velocity()
            telemetry.append({'frame': frame, 'phase': label, 'throttle': throttle,
                'brake': brake, 'speed_mps': math.sqrt(velocity.x ** 2 + velocity.y ** 2),
                'distance_m': ego.get_location().distance(obstacle.get_location()),
                'starts': executor.starts})
            # Match RGB frames to simulator ticks; never use the spectator window.
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                try:
                    last_image = frames.get(timeout=0.2)
                    if last_image.frame >= frame:
                        break
                except queue.Empty:
                    continue

        # Settle the trucks; first request then a safety stop from the detector.
        for _ in range(30):
            tick('settle')
        commit()
        for _ in range(30):
            tick('first_commit')
        executor.emergency_stop()
        events.append({'event': 'emergency_stop', 'frame': world.get_snapshot().frame})
        for _ in range(100):
            tick('braking')
        if collisions:
            raise AssertionError('Fixture collided before duplicate request')
        if telemetry[-1]['speed_mps'] > 0.2:
            raise AssertionError('Fixture did not stop before duplicate request')
        last_image.save_to_disk(str(folder / 'before_duplicate.png'))
        commit()
        hit_step = None
        for step in range(600):
            tick('after_duplicate')
            truck_hits = [event for event in collisions if event['other_actor_id'] == obstacle.id]
            if truck_hits and hit_step is None:
                hit_step = step
                last_image.save_to_disk(str(folder / 'collision.png'))
            if hit_step is not None and step >= hit_step + 10:
                break
        last_image.save_to_disk(str(folder / 'final.png'))
        truck_hits = [event for event in collisions if event['other_actor_id'] == obstacle.id]
        result = {'case': name, 'fault_injected': not protected,
                  'vehicle_blueprint': bp.id,
                  'camera_transform': str(camera.get_transform()),
                  'ego_transform': str(ego.get_transform()),
                  'obstacle_transform': str(obstacle.get_transform()),
                  'scope': 'isolated emergency-stop reset model, real CARLA physics',
                  'commit_requests': 2, 'physical_starts': executor.starts,
                  'truck_collision_events': len(truck_hits),
                  'collision_events': collisions, 'events': events,
                  'final_speed_mps': telemetry[-1]['speed_mps'],
                  'final_distance_m': telemetry[-1]['distance_m'],
                  'collision_image': 'collision.png' if truck_hits else None}
        (folder / 'telemetry.json').write_text(json.dumps(telemetry, indent=2))
        (folder / 'result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
        return result
    finally:
        if server:
            server.shutdown()
            server.server_close()
        for actor in reversed(actors):
            if actor.type_id.startswith('sensor.'):
                actor.stop()
            actor.destroy()
        world.apply_settings(original)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--carla-root', type=Path, default=Path('/home/jsy202/carla-0.9.13'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    # Own this process group; do not stop any pre-existing CARLA instance.
    import socket
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1', 2000)) == 0:
            raise RuntimeError('Port 2000 already in use; refusing to touch existing server')
    results = []
    for protected in (False, True):
        results.append(run_owned_server(args, protected))
    (args.output / 'comparison.json').write_text(json.dumps(results, indent=2))
    assert results[0]['truck_collision_events'] > 0, 'Fault did not cause a collision'
    assert results[1]['truck_collision_events'] == 0, 'Protected case collided'
    assert results[1]['physical_starts'] == 1


def run_owned_server(args, protected):
    name = 'fixed' if protected else 'vulnerable'
    with (args.output / ('carla_' + name + '.log')).open('w') as log:
        process = subprocess.Popen([str(args.carla_root / 'CarlaUE4.sh'),
            '/Game/Carla/Maps/Town06', '-RenderOffScreen', '-quality-level=Low',
            '-nosound', '-fps=20', '-carla-rpc-port=2000'],
            cwd=str(args.carla_root), stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True)
        try:
            deadline = time.monotonic() + 120
            while True:
                try:
                    # A client created before RPC startup can retain a stale connection.
                    client = carla.Client('127.0.0.1', 2000, worker_threads=2)
                    client.set_timeout(10)
                    client.get_world()
                    break
                except RuntimeError:
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise
                    time.sleep(1)
            client.set_timeout(60)
            return drive_case(client, args.output, protected)
        finally:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            # The launcher shell may exit before its child releases the RPC port.
            time.sleep(3)


if __name__ == '__main__':
    main()
