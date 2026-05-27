import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    shutil.which('iverilog') is None or shutil.which('vvp') is None,
    reason='iverilog or vvp not installed',
)


@pytest.fixture
def project_root():
    return Path(__file__).resolve().parents[1]


def _make_env(project_root):
    env = os.environ.copy()
    src = str(project_root / 'src')
    old = env.get('PYTHONPATH', '')
    env['PYTHONPATH'] = src + os.pathsep + old if old else src
    return env


def _run_cmd(cmd, cwd, env):
    result = subprocess.run(
        cmd, cwd=str(cwd), env=env, capture_output=True, text=True, shell=False,
    )
    if result.returncode != 0:
        pytest.fail(
            'Command failed: ' + ' '.join(cmd) + '\n'
            'cwd: ' + str(cwd) + '\n\n'
            'STDOUT:\n' + result.stdout + '\n\n'
            'STDERR:\n' + result.stderr
        )
    return result


def _load_config(path):
    cfg = path / 'example.json'
    if not cfg.exists():
        pytest.fail('Missing example.json in ' + str(path))
    with cfg.open('r', encoding='utf-8') as f:
        config = json.load(f)
    for src in config['sources']:
        if not (path / src).exists():
            pytest.fail('Missing Verilog source: ' + str(path / src))
    return config


def _run_iverilog(example_path, project_root):
    env = _make_env(project_root)
    config = _load_config(example_path)
    build = example_path / 'build'
    build.mkdir(exist_ok=True)
    vvp_out = build / 'sim.vvp'
    cmd = ['iverilog', '-g2012', '-o', str(vvp_out)]
    top = config.get('top')
    if top:
        cmd.extend(['-s', top])
    cmd.extend(config['sources'])
    _run_cmd(cmd, example_path, env)
    _run_cmd(['vvp', str(vvp_out)], example_path, env)
    for item in config.get('run', []):
        parts = shlex.split(item, posix=(os.name != 'nt'))
        if parts and parts[0] == 'python':
            parts[0] = sys.executable
        _run_cmd(parts, example_path, env)


def _run_example(example_path, project_root):
    if shutil.which('make') and (example_path / 'Makefile').exists():
        _run_cmd(['make', 'all'], example_path, _make_env(project_root))
    else:
        _run_iverilog(example_path, project_root)


def test_scoreboard_verify(project_root):
    _run_example(project_root / 'example' / 'scoreboard', project_root)


def test_fifo_occupancy(project_root):
    _run_example(project_root / 'example' / 'fifo_occupancy', project_root)


def test_fifo_latency(project_root):
    _run_example(project_root / 'example' / 'fifo_latency', project_root)
