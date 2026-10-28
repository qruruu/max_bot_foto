#!/usr/bin/env python3
"""Read Linux host counters, selected container state and backup timestamps only.

Run locally on the host. No listening port, Docker socket mount or remote agent.
"""
import argparse
import json
import re
import shutil
import ssl
import subprocess
import time
from datetime import UTC, datetime
from ipaddress import ip_address
from pathlib import Path


def command(args, *, data=None):
    result = subprocess.run(args, input=data, capture_output=True, check=True, timeout=100)
    return result.stdout


def cpu_counters(proc):
    lines = (proc / 'stat').read_text().splitlines()
    values = [int(value) for value in lines[0].split()[1:9]]
    return values, sum(line.startswith('cpu') and line[3:4].isdigit() for line in lines)


def cpu_percent(before, after):
    difference = [max(0, right - left) for left, right in zip(before, after, strict=True)]
    total = sum(difference)
    return (round(100 * (total - difference[3] - difference[4]) / total, 2) if total else 0,
            round(100 * difference[4] / total, 2) if total else 0)


def memory_counters(proc):
    values = {line.split(':')[0]: int(line.split()[1]) * 1024
              for line in (proc / 'meminfo').read_text().splitlines() if len(line.split()) >= 2}
    return {'memory_total': values['MemTotal'], 'memory_available': values['MemAvailable'],
            'swap_total': values.get('SwapTotal', 0),
            'swap_used': values.get('SwapTotal', 0) - values.get('SwapFree', 0)}


def network_counters(proc):
    rx = tx = 0
    for line in (proc / 'net/dev').read_text().splitlines()[2:]:
        name, values = line.split(':', 1)
        if name.strip().startswith(('lo', 'docker', 'br-', 'veth')):
            continue
        columns = values.split()
        rx += int(columns[0]); tx += int(columns[8])
    return rx, tx


def backup_status(config):
    try:
        state = Path(json.loads(config.read_text())['state_dir'])
    except (OSError, ValueError, KeyError):
        return {}
    def read(name):
        try:
            return json.loads((state / name).read_text())
        except (OSError, ValueError):
            return {}
    success, attempt, verification = read('last-success.json'), read('last-attempt.json'), read('last-verification.json')
    return {'last_success_at': success.get('finished_at') if success.get('success') else None,
            'last_attempt_ok': attempt.get('success'),
            'last_attempt_at': attempt.get('finished_at') or attempt.get('failed_at'),
            'verified_at': verification.get('verified_at') or verification.get('failed_at'),
            'verification_ok': verification.get('success')}


def service_status(compose):
    ids = command(compose + ['ps', '--all', '--quiet']).decode().split()
    if not ids:
        return []
    # A narrow template is intentional: never read configuration, environment or commands.
    template = '{{json .Config.Labels}}|{{json .State}}|{{.RestartCount}}'
    rows = command(['docker', 'inspect', '--format', template, *ids]).decode().splitlines()
    services = []
    for row in rows:
        labels, state, restarts = row.split('|')
        labels, state = json.loads(labels), json.loads(state)
        name = labels.get('com.docker.compose.service', '')
        if name == 'migrate':
            continue
        services.append({'name': name, 'running': state.get('Running', False),
            'health': state.get('Health', {}).get('Status', 'not_configured'),
            'restarts': int(restarts), 'oom_killed': state.get('OOMKilled', False)})
    return services


def sample(proc, disk_path, *, pause=time.sleep):
    first_cpu, cores = cpu_counters(proc)
    first_net = network_counters(proc)
    started = time.monotonic()
    pause(1)
    second_cpu, _ = cpu_counters(proc)
    second_net = network_counters(proc)
    elapsed = max(0.01, time.monotonic() - started)
    cpu, wait = cpu_percent(first_cpu, second_cpu)
    disk = shutil.disk_usage(disk_path)
    load = [float(value) for value in (proc / 'loadavg').read_text().split()[:3]]
    return {'source': 'linux-host', 'cpu_percent': cpu, 'iowait_percent': wait, 'cpu_cores': cores,
            'load_1': load[0], 'load_5': load[1], 'load_15': load[2],
            'uptime_seconds': float((proc / 'uptime').read_text().split()[0]),
            'disk_total': disk.total, 'disk_free': disk.free, 'disk_used': disk.used,
            'network_rx_bytes_sec': max(0, second_net[0] - first_net[0]) / elapsed,
            'network_tx_bytes_sec': max(0, second_net[1] - first_net[1]) / elapsed,
            **memory_counters(proc)}



def ssh_events():
    try:
        raw = command(['journalctl', '-u', 'ssh', '-u', 'sshd', '--since', '-2 minutes',
                       '--no-pager', '-o', 'json', '--lines', '500']).decode()
    except (OSError, subprocess.SubprocessError):
        return [], False
    events = []
    for line in raw.splitlines():
        try:
            item = json.loads(line)
            message = item.get('MESSAGE', '')
            match = re.search(r'(Failed|Accepted) (?:password|publickey) for (?:invalid user )?(\S+) from (\S+) port', message)
            if not match:
                continue
            ip = str(ip_address(match[3]))
            at = datetime.fromtimestamp(int(item['__REALTIME_TIMESTAMP']) / 1_000_000, UTC).isoformat()
            events.append({'id': 'ssh:' + item['__CURSOR'], 'kind': 'SSH_FAILED' if match[1] == 'Failed' else 'SSH_SUCCESS',
                'ip_address': ip, 'actor_label': match[2][:100], 'actor_key': 'ssh:' + match[2][:100],
                'resource': 'SSH', 'at': at, 'product': 'host'})
        except (ValueError, KeyError, TypeError):
            continue
    return events, True


def edge_events(compose):
    events = []
    try:
        ids = command(compose + ['ps', '--quiet', 'web', 'appeals-web']).decode().split()
        for id in ids:
            for line in command(['docker', 'logs', '--since', '2m', '--tail', '1000', id]).decode().splitlines():
                try:
                    item = json.loads(line)
                    if not item.get('metka_security'):
                        continue
                    ip = str(ip_address(item['ip']))
                    if item['kind'] not in {'HTTP_PROBE', 'EDGE_RATE_LIMIT'}:
                        continue
                    events.append({'id': 'edge:' + item['id'], 'kind': item['kind'], 'ip_address': ip,
                        'actor_label': 'Не авторизован', 'actor_key': '', 'resource': item.get('resource', '')[:60],
                        'at': item['time'], 'status_code': int(item['status']), 'product': 'edge'})
                except (ValueError, KeyError, TypeError):
                    continue
    except (OSError, subprocess.SubprocessError):
        return events, False
    return events, bool(ids)


def listening_ports():
    try:
        raw = command(['ss', '-H', '-lnt']).decode()
    except (OSError, subprocess.SubprocessError):
        return None
    result = []
    for line in raw.splitlines():
        address = line.split()[3]
        host, _, port = address.rpartition(':')
        if port.isdigit():
            result.append({'port': int(port), 'public': host in {'0.0.0.0', '*', '[::]', '::'},
                           'binding': host[:50]})
    return result


def certificates(paths):
    result = []
    for path in paths:
        try:
            value = command(['openssl', 'x509', '-in', str(path), '-noout', '-enddate']).decode().strip().split('=', 1)[1]
            expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(value), UTC).isoformat()
            result.append({'name': path.parent.name, 'expires_at': expires})
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            result.append({'name': path.parent.name, 'expires_at': None})
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, default=Path('/root/max_bot_foto'))
    parser.add_argument('--disk', type=Path, default=Path('/'))
    parser.add_argument('--proc', type=Path, default=Path('/proc'))
    parser.add_argument('--backup-config', type=Path, default=Path('/etc/max-foto-backup/config.json'))
    parser.add_argument('--certificate', type=Path, action='append', default=[])
    parser.add_argument('--print-only', action='store_true')
    args = parser.parse_args()
    if not args.project.is_absolute() or not args.disk.is_absolute():
        raise SystemExit('Absolute paths required')
    compose = ['docker', 'compose', '--project-directory', str(args.project), '--profile', '*']
    payload = sample(args.proc, args.disk)
    payload['services'] = service_status(compose)
    payload['backup'] = backup_status(args.backup_config)
    ssh, ssh_available = ssh_events()
    edge, edge_available = edge_events(compose)
    payload['security_events'] = ssh + edge
    payload['security_sources'] = {'ssh': ssh_available, 'edge': edge_available}
    payload['ports'] = listening_ports()
    payload['certificates'] = certificates(args.certificate or [Path('/etc/letsencrypt/live/metka.yunorit.ru/fullchain.pem'),
        Path('/etc/letsencrypt/live/metka-signal.yunorit.ru/fullchain.pem')])
    try:
        payload['changed_source_files'] = len(command(['git', '-C', str(args.project), 'status', '--porcelain', '--untracked-files=no']).decode().splitlines())
    except (OSError, subprocess.SubprocessError):
        payload['changed_source_files'] = None
    raw = json.dumps(payload, allow_nan=False).encode()
    if args.print_only:
        print(raw.decode())
    else:
        command(compose + ['exec', '-T', 'api', 'python', '-m', 'app.platform_monitor', 'ingest'], data=raw)
        print('Host monitoring updated')


if __name__ == '__main__':
    main()
