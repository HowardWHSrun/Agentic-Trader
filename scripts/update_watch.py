#!/usr/bin/env python3
"""Apply an already sanitized, public-only hard review or soft-check status.

Never pass raw brokerage responses, private reports or account records here.
Narrative privacy requires explicit human review; schema checks are not a prose
sanitizer. This updates local files only, never the deployed website.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from test_watch import HARD_FIELDS, SOFT_FIELDS, history_id, timestamp, validate

ROOT = Path(__file__).resolve().parents[1]


def _atomic_json(path, value, immutable=False):
    """Publish a complete file, never a truncated file or overwritten original.

    A history file may remain unindexed if the later current-file replacement
    fails. It is complete, validated and immutable; a retry can safely reuse it.
    """
    payload = json.dumps(value, indent=2, allow_nan=False) + '\n'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.' + path.name + '.', suffix='.tmp',
                                         delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if immutable:
            # Atomic no-clobber creation also protects against a competing writer.
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _check_paths(root, path):
    for target in (root / 'docs', root / 'docs/data', root / 'docs/data/watch-history', path):
        if target.is_symlink():
            raise ValueError('Public update paths must not be symlinks')


def _validate_history(data, root):
    for index, item in enumerate(data['score_history']):
        history_id(item['id'])
        path = root / 'docs' / item['path']
        _check_paths(root, path)
        review = json.loads(path.read_text())
        historical = dict(data, last_hard_check=review,
                          score_history=data['score_history'][:index + 1])
        validate(historical)


def update(mode, incoming, root=ROOT):
    if mode not in {'hard', 'soft'}:
        raise ValueError('Mode must be hard or soft')
    root = Path(root)
    path = root / 'docs/data/watch.json'
    _check_paths(root, path)
    data = json.loads(path.read_text())
    validate(data)
    _validate_history(data, root)
    if mode == 'soft':
        if not isinstance(incoming, dict) or set(incoming) != SOFT_FIELDS:
            raise ValueError('Soft input must contain only the six public status fields')
        checked = timestamp(incoming['checked_at'])
        old = data.get('last_soft_check')
        if old and checked < timestamp(old['checked_at']):
            raise ValueError('Do not replace a newer soft check')
        data['last_soft_check'] = incoming
    else:
        if not isinstance(incoming, dict) or set(incoming) - HARD_FIELDS:
            raise ValueError('Unexpected hard-review fields; provide a public-only export')
        # Validate before any path construction or filesystem access using this ID.
        ident = history_id(incoming.get('id'))
        published = timestamp(incoming.get('publication_timestamp'))
        history = root / 'docs/data/watch-history' / (ident + '.json')
        _check_paths(root, history)
        if history.exists() and json.loads(history.read_text()) != incoming:
            raise ValueError('Original publication immutable; append a correction with a new ID')
        old = data.get('last_hard_check')
        if old and published < timestamp(old['publication_timestamp']):
            raise ValueError('Do not replace a newer hard review')
        data['last_hard_check'] = incoming
        if not any(x['id'] == ident for x in data['score_history']):
            data['score_history'].append({'id': ident,
                'publication_timestamp': incoming['publication_timestamp'],
                'path': 'data/watch-history/' + ident + '.json'})
    validate(data)
    if mode == 'hard':
        history.parent.mkdir(exist_ok=True)
        if not history.exists():
            _atomic_json(history, incoming, immutable=True)
    _atomic_json(path, data)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['hard', 'soft'])
    parser.add_argument('input', type=Path)
    args = parser.parse_args()
    update(args.mode, json.loads(args.input.read_text()))
