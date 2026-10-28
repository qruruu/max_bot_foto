"""Sampler reads selected counters and security metadata, never container secrets."""
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location('host_sampler', Path(__file__).parents[2] / 'ops/monitor/max_foto_monitor.py')
sampler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sampler)


def test_cpu_percent_separates_iowait_and_idle():
    cpu, wait = sampler.cpu_percent([0]*8, [25,0,25,40,10,0,0,0])
    assert cpu == 50 and wait == 10
    assert sampler.cpu_percent([0]*8,[0]*8) == (0,0)


def test_ssh_parser_deduplicable_identifiers_but_no_raw_logs(monkeypatch):
    message={'MESSAGE':'Accepted publickey for root from 198.51.100.44 port 4500 ssh2: SECRET_KEY_FINGERPRINT',
             '__CURSOR':'cursor-one','__REALTIME_TIMESTAMP':'1793180000000000'}
    monkeypatch.setattr(sampler,'command',lambda args:json.dumps(message).encode())
    events,available=sampler.ssh_events()
    assert available and events[0]['kind']=='SSH_SUCCESS'
    assert events[0]['ip_address']=='198.51.100.44'
    assert events[0]['id']=='ssh:cursor-one'
    assert 'SECRET' not in json.dumps(events) and 'MESSAGE' not in events[0]


def test_narrow_container_inspection_has_no_environment_or_logs(monkeypatch):
    calls=[]
    def command(args):
        calls.append(args)
        return b'id1' if args[-1]=='--quiet' else b'{"com.docker.compose.service":"api"}|{"Running":true,"Health":{"Status":"healthy"}}|2'
    monkeypatch.setattr(sampler,'command',command)
    result=sampler.service_status(['docker','compose'])
    assert result[0]['restarts']==2 and result[0]['health']=='healthy'
    assert '.Config.Env' not in str(calls) and '.Config.Labels' in str(calls)


def test_backup_reads_result_markers_without_secret_config(tmp_path):
    config = tmp_path / 'config.json'
    state = tmp_path / 'state'
    state.mkdir()
    config.write_text(json.dumps({'state_dir':str(state),'token':'DO_NOT_PUBLISH'}))
    (state/'last-success.json').write_text(json.dumps({'success':True,'finished_at':'2026-10-28T10:00:00Z','encryption_key':'SECRET'}))
    result=sampler.backup_status(config)
    assert result['last_success_at']=='2026-10-28T10:00:00Z'
    assert 'SECRET' not in json.dumps(result) and 'DO_NOT_PUBLISH' not in json.dumps(result)
