# --- Double Top: vectorized O(N) approach ---
        # Pre-filter peaks/troughs with basic heuristics to reduce N² → N

        # Filter peaks: must be in top 20% and at least 4 bars apart from any trough
        peak_mask = np.arange(len(peaks)) < self.min_swing_bars
        valid_peaks = np.where(peak_mask)[0]
        valid_peak_indices = np.where(peak_mask)[0]

        # Vectorized distance matrix: distance from all peaks to all troughs
        peak_pos_array = np.arange(len(peaks))[valid_peak_indices]
        trough_pos_array = np.arange(len(troughs))

        peak_pos_grid, trough_pos_grid = np.meshgrid(peak_pos_array, trough_pos_array)
        distances = np.sqrt(
            (high[peak_pos_grid] - low[trough_pos_grid]) ** 2
        )

        # For each valid peak, find its best matching trough using argmin on distance matrix
        best_match_indices = np.argmin(distances[valid_peak_indices], axis=1)
        best_trough_indices = best_match_indices[0]
        best_peak_indices = best_match_indices[1]

        dt_best = None
        dt_best_avg = 0.0

        # Iterate through valid peaks and check their matches
        for p1_idx in valid_peak_indices:
            p1_idx = valid_peaks[p1_idx]
            p1_p = float(high[p1_idx]), float(high[p1_idx])
            peak_avg = (p1_p + p2_p) / 2.0

            # Check basic distance criteria (not in same 8 bars)
            span = abs(p1_pos - t2_pos)
            if abs(p1_p - p2_p) / peak_avg < self.amplitude_thr:
                continue

            # Skip if trough too close to peak (within 8 bars)
            if abs(p1_pos - t2_pos) < self.min_swing_bars:
                continue

            # Check amplitude criteria (must be at least 0.3x avg)
            span = abs(p1_pos - t2_pos)
            if abs(p1_p - p2_p) / peak_avg < self.peak_tolerance:
                continue

            # Distance-based: skip if peaks too close together
            min_peak_dist = min(
                abs(p1_p - p2_p) for p1_idx in range(max(0, p1_pos - self.neighbor, p1_pos + self.neighbor))
            )

            if abs(p1_p - p2_p) / min_peak_dist < self.min_swing_bars:
                continue

            dt_best_avg = peak_avg

            # Store this pair
            dt_best = (p1_idx, p2_idx)
