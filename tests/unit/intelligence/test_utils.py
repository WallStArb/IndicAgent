"""Tests for shared intelligence utilities."""

import numpy as np

from src.intelligence.utils import find_peaks, find_troughs, is_num

# ─── find_peaks ────────────────────────────────────────────────


class TestFindPeaks:
    def test_basic_peak(self):
        data = np.array([1, 2, 3, 4, 5, 4, 3, 2, 1, 2, 3, 4, 3, 2, 1])
        peaks = find_peaks(data, n=2)
        assert 4 in peaks  # index 4 = value 5

    def test_tied_peak_detected(self):
        """Bar tying its neighbor at a plateau edge should still be detected."""
        # Plateau of 5s flanked by lower values
        data = np.array([1.0, 2, 3, 5, 5, 5, 3, 2, 1, 0, 0, 0, 0, 0, 0])
        peaks = find_peaks(data, n=2)
        assert len(peaks) > 0
        assert all(data[p] == 5.0 for p in peaks)

    def test_flat_line_no_peaks(self):
        """Completely flat data — no bar has a strict inequality."""
        data = np.full(20, 100.0)
        assert find_peaks(data, n=3) == []

    def test_short_data_no_peaks(self):
        data = np.array([1, 2, 3])
        assert find_peaks(data, n=2) == []

    def test_sinusoidal(self):
        """Sinusoidal data should produce peaks at approximately every half cycle."""
        t = np.linspace(0, 4 * np.pi, 100)
        data = np.sin(t)
        peaks = find_peaks(data, n=5)
        assert len(peaks) >= 1
        for p in peaks:
            assert data[p] > 0.8  # near the top of the sine

    def test_single_spike(self):
        data = np.zeros(20)
        data[10] = 1.0
        peaks = find_peaks(data, n=3)
        assert peaks == [10]


# ─── find_troughs ──────────────────────────────────────────────


class TestFindTroughs:
    def test_basic_trough(self):
        data = np.array([5, 4, 3, 2, 1, 2, 3, 4, 5, 4, 3, 2, 3, 4, 5])
        troughs = find_troughs(data, n=2)
        assert 4 in troughs  # index 4 = value 1

    def test_tied_trough_detected(self):
        """Plateau at the bottom should be detected."""
        data = np.array([5.0, 4, 3, 1, 1, 1, 3, 4, 5, 6, 6, 6, 6, 6, 6])
        troughs = find_troughs(data, n=2)
        assert len(troughs) > 0
        assert all(data[t] == 1.0 for t in troughs)

    def test_flat_line_no_troughs(self):
        data = np.full(20, 100.0)
        assert find_troughs(data, n=3) == []

    def test_single_dip(self):
        data = np.ones(20)
        data[10] = 0.0
        troughs = find_troughs(data, n=3)
        assert troughs == [10]


# ─── is_num ────────────────────────────────────────────────────


class TestIsNum:
    def test_int(self):
        assert is_num(42) is True

    def test_float(self):
        assert is_num(3.14) is True

    def test_none(self):
        assert is_num(None) is False

    def test_string(self):
        assert is_num("42") is False

    def test_bool_is_int_subclass(self):
        # In Python, bool is a subclass of int — is_num returns True
        assert is_num(True) is True

    def test_nan_rejected(self):
        assert is_num(float("nan")) is False

    def test_inf_rejected(self):
        assert is_num(float("inf")) is False

    def test_negative_inf_rejected(self):
        assert is_num(float("-inf")) is False

    def test_zero(self):
        assert is_num(0) is True

    def test_negative_float(self):
        assert is_num(-3.14) is True
