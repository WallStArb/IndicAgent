"use client";

interface SparklineProps {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
  className?: string;
}

/**
 * Tiny inline SVG sparkline chart.
 * Renders a polyline from an array of numbers.
 * No external dependencies.
 */
export function Sparkline({
  values,
  width = 48,
  height = 16,
  color = "var(--text-secondary)",
  className,
}: SparklineProps) {
  if (values.length < 2) {
    return (
      <svg
        width={width}
        height={height}
        className={className}
        viewBox={`0 0 ${width} ${height}`}
      >
        <line
          x1={0}
          y1={height / 2}
          x2={width}
          y2={height / 2}
          stroke={color}
          strokeWidth={1}
          opacity={0.3}
        />
      </svg>
    );
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const pad = 1; // pixel padding top/bottom

  const points = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * width;
      const y = pad + ((max - v) / range) * (height - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  // Determine if trending up or down for gradient
  const trending = values[values.length - 1] >= values[0];
  const autoColor =
    color === "auto"
      ? trending
        ? "var(--green)"
        : "var(--red)"
      : color;

  return (
    <svg
      width={width}
      height={height}
      className={className}
      viewBox={`0 0 ${width} ${height}`}
    >
      <polyline
        points={points}
        fill="none"
        stroke={autoColor}
        strokeWidth={1.2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Current value dot */}
      <circle
        cx={(width).toFixed(1)}
        cy={
          (
            pad +
            ((max - values[values.length - 1]) / range) * (height - pad * 2)
          ).toFixed(1)
        }
        r={1.5}
        fill={autoColor}
      />
    </svg>
  );
}
