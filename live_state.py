# -*- coding: utf-8 -*-
"""
Live state builder: assembles current-data.json in real time from the
0xF6 key/value packets the game streams to the game server.

Two components:

StreamParser
    Incremental parser for a single TCP byte stream. Handles:
    - fragmentation: one message split across several TCP segments
    - coalescing: several messages packed into one segment
    - garbage/resync: skips bytes until a plausible 0xF6 message
    - retransmission/duplication: segments are ordered by TCP sequence
    - gaps: segments captured out of order are stashed; if the hole is
      not filled within GAP_TIMEOUT seconds, processing continues with
      a best-effort skip (the lost bytes are reported in stats)

LiveStateBuilder
    Applies parsed commands to an in-memory dict and atomically persists
    it to current-data.json on every change. set_profile / set_password /
    set_id go to session metadata only (the password is never written to
    the data file).

Value types are preserved exactly as the game sends them (values arrive
as strings over the wire) - the custom map controls the real types.
"""

import json
import os
import tempfile
import threading
import time

MSG_MAGIC = 0xF6

# Command ids of the game protocol (see parse_one_packet in app.py)
CMD_SET_PROFILE = 0x01
CMD_SET_PASSWORD = 0x02
CMD_SET_ID = 0x03
CMD_FLUSH = 0x05
CMD_EVENT_06 = 0x06
CMD_SET_VALUE = 0x07
CMD_FINALIZE = 0x08

# How long a sequence gap may stay unfilled before we force-flush
# pending out-of-order segments (seconds)
GAP_TIMEOUT = 5.0

# Sanity cap for a single field inside a message. A desynced stream can
# claim absurd lengths which would stall parsing forever - treat such
# claims as invalid and resync instead.
MAX_FIELD_LEN = 16 * 1024


# ==========================================
# Message parsing (strict, stream-oriented)
# ==========================================
def _u16(data, off):
    return data[off] | (data[off + 1] << 8)


def _decode_str(data, off, slen):
    return data[off:off + slen].decode('utf-8', errors='replace')


def try_parse_message(buf):
    """Parse one 0xF6 message from the very start of buf.

    Returns (status, message, consumed):
      'ok'         - message parsed; consumed bytes belong to it
      'incomplete' - need more bytes to decide
      'invalid'    - buf[0] cannot start a valid message; resync required
    """
    if len(buf) < 1:
        return 'incomplete', None, 0
    if buf[0] != MSG_MAGIC:
        return 'invalid', None, 0
    if len(buf) < 2:
        return 'incomplete', None, 0
    cmd = buf[1]

    if cmd in (CMD_SET_PROFILE, CMD_SET_PASSWORD):
        if len(buf) < 4:
            return 'incomplete', None, 0
        slen = _u16(buf, 2)
        if slen > MAX_FIELD_LEN:
            return 'invalid', None, 0
        end = 4 + slen
        if len(buf) < end:
            return 'incomplete', None, 0
        if len(buf) == end:
            # A trailing NUL terminator may still arrive with the next
            # segment - wait for one more byte to decide.
            return 'incomplete', None, 0
        consumed = end + 1 if buf[end] == 0 else end
        kind = 'set_profile' if cmd == CMD_SET_PROFILE else 'set_password'
        return 'ok', {'cmd': kind, 'value': _decode_str(buf, 4, slen)}, consumed

    if cmd == CMD_SET_ID:
        if len(buf) < 8:
            return 'incomplete', None, 0
        return 'ok', {'cmd': 'set_id', 'value': int.from_bytes(buf[4:8], 'little')}, 8

    if cmd == CMD_FLUSH:
        if len(buf) < 4:
            return 'incomplete', None, 0
        return 'ok', {'cmd': 'flush'}, 4

    if cmd == CMD_FINALIZE:
        if len(buf) < 4:
            return 'incomplete', None, 0
        return 'ok', {'cmd': 'finalize'}, 4

    if cmd == CMD_EVENT_06:
        if len(buf) < 5:
            return 'incomplete', None, 0
        return 'ok', {'cmd': 'event_06', 'value': buf[4]}, 5

    if cmd == CMD_SET_VALUE:
        if len(buf) < 6:
            return 'incomplete', None, 0
        tlen = _u16(buf, 2)
        klen = _u16(buf, 4)
        if klen > MAX_FIELD_LEN:
            return 'invalid', None, 0
        if len(buf) < 8 + klen:
            return 'incomplete', None, 0
        vlen = _u16(buf, 6 + klen)
        if vlen > MAX_FIELD_LEN:
            return 'invalid', None, 0
        struct_total = 8 + klen + vlen
        msg_total = 4 + tlen
        if msg_total < struct_total:
            # Header contradicts the key/value structure -> desynced stream
            return 'invalid', None, 0
        if len(buf) < msg_total:
            return 'incomplete', None, 0
        key = _decode_str(buf, 6, klen)
        value = _decode_str(buf, 8 + klen, vlen)
        return 'ok', {'cmd': 'set_value', 'key': key, 'value': value}, msg_total

    # Unknown command: framing cannot be trusted, caller must resync
    return 'invalid', None, 0


# ==========================================
# StreamParser: one TCP connection
# ==========================================
class StreamParser:
    """Incremental 0xF6-message parser for a single TCP byte stream."""

    def __init__(self):
        self._buf = b''
        self._expected_seq = None
        self._pending = {}      # seq -> payload, waiting for a hole to fill
        self._gap_since = None  # timestamp of the oldest unfilled hole
        self.last_seen = time.time()

    def feed(self, payload, seq):
        """Feed one TCP segment (payload bytes starting at seq).

        Returns (messages, stats):
          messages - list of parsed message dicts, in stream order
          stats    - {'dropped': int, 'gaps_skipped': int,
                      'unknown_cmds': [hex strings]}
        """
        messages = []
        stats = {'dropped': 0, 'gaps_skipped': 0, 'unknown_cmds': []}

        self.last_seen = time.time()
        # Gap timeout recovery also has to run on empty segments (e.g. ACKs)
        self._maybe_force_drain(messages, stats)

        if not payload:
            return messages, stats

        if self._expected_seq is None:
            # First data segment we see defines the stream start
            self._expected_seq = seq

        ahead = (seq - self._expected_seq) & 0xFFFFFFFF
        if ahead == 0:
            self._append(payload, messages, stats)
            self._advance(len(payload))
            self._drain_pending(messages, stats)
        elif ahead < 0x80000000:
            # Gap: this segment starts beyond what we have seen
            self._pending[seq] = bytes(payload)
            if self._gap_since is None:
                self._gap_since = time.time()
            if len(self._pending) > 128:
                self._force_drain(messages, stats)
        else:
            # Segment starts behind the expected position:
            # duplicate or partial retransmission overlap
            behind = (self._expected_seq - seq) & 0xFFFFFFFF
            if behind < len(payload):
                fresh = bytes(payload[behind:])
                self._append(fresh, messages, stats)
                self._advance(len(fresh))
                self._drain_pending(messages, stats)
            # else: fully duplicated old data - nothing new to do

        return messages, stats

    def finish(self):
        """Flush everything that can still be parsed (connection closed)."""
        messages = []
        stats = {'dropped': 0, 'gaps_skipped': 0, 'unknown_cmds': []}
        self._force_drain(messages, stats)
        return messages, stats

    # ----- internal -----
    def _advance(self, n):
        self._expected_seq = (self._expected_seq + n) & 0xFFFFFFFF

    def _append(self, data, messages, stats):
        self._buf += data
        while self._buf:
            status, msg, consumed = try_parse_message(self._buf)
            if status == 'ok':
                messages.append(msg)
                self._buf = self._buf[consumed:]
            elif status == 'incomplete':
                break
            else:  # invalid -> resync to the next magic byte
                if self._buf[0] == MSG_MAGIC and len(stats['unknown_cmds']) < 10:
                    stats['unknown_cmds'].append(hex(self._buf[1]) if len(self._buf) > 1 else '0xF6')
                idx = self._buf.find(bytes([MSG_MAGIC]), 1)
                if idx == -1:
                    stats['dropped'] += len(self._buf)
                    self._buf = b''
                else:
                    stats['dropped'] += idx
                    self._buf = self._buf[idx:]

    def _drain_pending(self, messages, stats):
        """Consume stashed segments that are contiguous now."""
        while self._expected_seq in self._pending:
            payload = self._pending.pop(self._expected_seq)
            self._append(payload, messages, stats)
            self._advance(len(payload))
            if not self._pending:
                self._gap_since = None

    def _maybe_force_drain(self, messages, stats):
        if self._pending and self._gap_since is not None:
            if time.time() - self._gap_since > GAP_TIMEOUT:
                self._force_drain(messages, stats)

    def _force_drain(self, messages, stats):
        """Best-effort recovery: consume stashed segments in stream order,
        jumping over holes that never got filled."""
        if not self._pending:
            self._gap_since = None
            return
        seqs = sorted(self._pending, key=lambda s: (s - self._expected_seq) & 0xFFFFFFFF)
        for s in seqs:
            payload = self._pending.pop(s)
            if s != self._expected_seq:
                stats['gaps_skipped'] += 1
                self._expected_seq = s
                # Whatever is buffered is a partial message whose middle
                # bytes fell into the lost hole - it can never parse.
                self._buf = b''
            self._append(payload, messages, stats)
            self._advance(len(payload))
        self._gap_since = None


# ==========================================
# LiveStateBuilder: state -> current-data.json
# ==========================================
class LiveStateBuilder:
    """Keeps the live profile state and persists it atomically on change."""

    def __init__(self, file_path):
        self._path = file_path
        self._lock = threading.RLock()
        self._state = {}
        self._started = False
        self._meta = {
            'profile': None,
            'password': None,   # in-memory only, never persisted to disk
            'player_id': None,
            'last_update': 0,
            'updates_applied': 0,
            'packets_seen': 0,
            'events_06': [],
            'last_error': None,
            'dropped_bytes': 0,
            'gaps_skipped': 0,
            'unknown_cmds': [],
        }

    # ----- lifecycle -----
    def init_from_file(self, source_path):
        """Seed the state from the server mirror (current.json)."""
        state = None
        try:
            with open(source_path, 'r', encoding='utf-8-sig') as f:
                state = json.load(f)
        except Exception:
            state = None
        with self._lock:
            self._state = state if isinstance(state, dict) else {}
            self._started = True
            self._meta['updates_applied'] = 0
            self._meta['packets_seen'] = 0
            self._meta['events_06'] = []
            self._meta['last_error'] = None
            self._write()

    def load_existing(self):
        """Load our own previous output (app restart mid-session)."""
        try:
            with open(self._path, 'r', encoding='utf-8-sig') as f:
                state = json.load(f)
        except Exception:
            return False
        with self._lock:
            if isinstance(state, dict):
                self._state = state
                self._started = True
                return True
        return False

    # ----- packet application -----
    def apply(self, msg):
        """Apply one parsed message. Returns True if the data file changed."""
        if not isinstance(msg, dict):
            return False
        with self._lock:
            self._meta['packets_seen'] += 1
            cmd = msg.get('cmd')

            if cmd == 'set_value':
                key = msg.get('key')
                if key is None:
                    return False
                self._state[key] = msg.get('value')
                self._meta['updates_applied'] += 1
                self._write()
                return True

            if cmd == 'set_profile':
                self._meta['profile'] = msg.get('value')
            elif cmd == 'set_password':
                self._meta['password'] = msg.get('value')
            elif cmd == 'set_id':
                self._meta['player_id'] = msg.get('value')
            elif cmd == 'event_06':
                ev = self._meta['events_06']
                ev.append({'t': int(time.time()), 'value': msg.get('value')})
                del ev[:-50]
            elif cmd in ('flush', 'finalize'):
                # Commit point: make sure everything is on disk
                self._write()
            return False

    def note_stream_stats(self, stats):
        """Accumulate StreamParser stats for diagnostics."""
        if not stats:
            return
        with self._lock:
            self._meta['dropped_bytes'] += stats.get('dropped', 0)
            self._meta['gaps_skipped'] += stats.get('gaps_skipped', 0)
            for u in stats.get('unknown_cmds', []):
                if len(self._meta['unknown_cmds']) < 50 and u not in self._meta['unknown_cmds']:
                    self._meta['unknown_cmds'].append(u)

    # ----- inspection -----
    def to_dict(self):
        with self._lock:
            return json.loads(json.dumps(self._state))

    def status(self):
        with self._lock:
            return {
                'exists': os.path.exists(self._path),
                'started': self._started,
                'last_update': self._meta['last_update'],
                'updates_applied': self._meta['updates_applied'],
                'packets_seen': self._meta['packets_seen'],
                'profile': self._meta['profile'],
                'player_id': self._meta['player_id'],
                'events_06': list(self._meta['events_06'][-10:]),
                'dropped_bytes': self._meta['dropped_bytes'],
                'gaps_skipped': self._meta['gaps_skipped'],
                'unknown_cmds': list(self._meta['unknown_cmds']),
                'last_error': self._meta['last_error'],
            }

    # ----- persistence -----
    def _write(self):
        """Atomic write: temp file in the same directory + os.replace."""
        try:
            directory = os.path.dirname(self._path) or '.'
            fd, tmp_path = tempfile.mkstemp(dir=directory, prefix='.current-data-', suffix='.tmp')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(self._state, f, indent=4, ensure_ascii=False)
                os.replace(tmp_path, self._path)
                self._meta['last_update'] = int(time.time())
                self._meta['last_error'] = None
            except Exception:
                raise
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
        except Exception as e:
            self._meta['last_error'] = str(e)
