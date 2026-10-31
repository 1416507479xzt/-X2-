"""AimDK v1.0.0 VAD PCM assembly, independent of ROS and dialogue logic."""

from dataclasses import dataclass
import time


PCM_BYTES_PER_SECOND = 16000 * 2  # S16LE, mono


@dataclass(frozen=True)
class VadUtterance:
    stream_id: int
    pcm: bytes
    packet_count: int
    elapsed_seconds: float

    @property
    def audio_seconds(self):
        return len(self.pcm) / PCM_BYTES_PER_SECOND


class VadAssembler:
    """Collect one bounded utterance from ProcessedAudioOutput messages.

    v1.0.0 uses stream_id=1 for the onboard microphone. A later SDK may use
    another value, so the caller chooses the stream explicitly.
    """

    def __init__(self, stream_id=1, max_seconds=20):
        if stream_id < 0 or max_seconds <= 0:
            raise ValueError("invalid VAD stream or duration limit")
        self.stream_id = stream_id
        self.max_bytes = int(max_seconds * PCM_BYTES_PER_SECOND)
        self.max_seconds = max_seconds
        self.reset()
        self.discarded = 0

    def reset(self):
        self._pcm = bytearray()
        self._started = None
        self._packets = 0
        self._dropping = False

    def feed(self, stream_id, state, audio_data, now=None):
        """Return a complete utterance at END, or None; never return stale audio."""
        if stream_id != self.stream_id:
            return None
        now = time.monotonic() if now is None else now
        if state == 0:
            return None
        if state == 1:
            self.reset()
            self._started = now
        elif self._dropping:
            if state == 3:
                self.reset()
            return None
        elif state == 2 and self._started is None:
            # A best-effort subscriber can miss BEGIN; recover this utterance.
            self._started = now
        elif state == 3 and self._started is None:
            return None
        elif state not in (1, 2, 3):
            return None

        chunk = bytes(audio_data)
        if (now - self._started > self.max_seconds or
                len(self._pcm) + len(chunk) > self.max_bytes):
            self.discarded += 1
            self.reset()
            self._dropping = state != 3
            return None
        self._pcm.extend(chunk)
        self._packets += 1
        if state != 3:
            return None
        result = VadUtterance(stream_id, bytes(self._pcm), self._packets,
                              max(0.0, now - self._started))
        self.reset()
        return result
