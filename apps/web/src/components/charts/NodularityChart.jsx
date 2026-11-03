import { useMemo } from "react";
import "./NodularityChart.css";

/*
  Props:
  - data: [{ label: string, value: number }]   // value = nodularity % from your CV pipeline
  - range: "7D" | "30D"                         // controlled range, optional
  - onRangeChange: (range) => void              // optional, called when user clicks 7D/30D
*/

const VB_W = 1000;
const VB_H = 300;
const PAD_X = 40;
const PAD_TOP = 24;
const PAD_BOTTOM = 36;

// Catmull-Rom -> cubic Bezier, stays close to real points (minimal overshoot)
function smoothPath(points) {
  if (points.length < 2) return "";
  let d = `M${points[0][0]},${points[0][1]}`;
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[i - 1] || points[i];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[i + 2] || p2;

    const cp1x = p1[0] + (p2[0] - p0[0]) / 6;
    const cp1y = p1[1] + (p2[1] - p0[1]) / 6;
    const cp2x = p2[0] - (p3[0] - p1[0]) / 6;
    const cp2y = p2[1] - (p3[1] - p1[1]) / 6;

    d += ` C${cp1x},${cp1y} ${cp2x},${cp2y} ${p2[0]},${p2[1]}`;
  }
  return d;
}

export default function NodularityChart({ data = [], range = "30D", onRangeChange }) {
  const { linePath, areaPath, points, yTicks } = useMemo(() => {
    if (!data.length) return { linePath: "", areaPath: "", points: [], yTicks: [] };

    const values = data.map((d) => d.value);
    const rawMin = Math.min(...values);
    const rawMax = Math.max(...values);

    // pad the y-range so the spline can never touch the viewBox edge
    let yMin = Math.max(0, Math.floor((rawMin - 5) / 10) * 10);
    let yMax = Math.min(100, Math.ceil((rawMax + 5) / 10) * 10);
    if (yMin === yMax) {
      yMin = Math.max(0, yMin - 10);
      yMax = Math.min(100, yMax + 10);
    }

    const chartW = VB_W - PAD_X * 2;
    const chartH = VB_H - PAD_TOP - PAD_BOTTOM;

    const toXY = (i, value) => {
      const x = PAD_X + (data.length === 1 ? chartW / 2 : (i / (data.length - 1)) * chartW);
      const y = PAD_TOP + chartH - ((value - yMin) / (yMax - yMin)) * chartH;
      return [x, y];
    };

    const pts = data.map((d, i) => toXY(i, d.value));
    const line = smoothPath(pts);
    const baseline = VB_H - PAD_BOTTOM;
    // A single data point has no line/area — avoid emitting a path that
    // starts with "L" (invalid SVG, console error).
    const area = pts.length < 2 ? "" : `${line} L${pts[pts.length - 1][0]},${baseline} L${pts[0][0]},${baseline} Z`;

    const tickCount = 4;
    const ticks = Array.from({ length: tickCount }, (_, i) => {
      const val = yMax - (i * (yMax - yMin)) / (tickCount - 1);
      const y = PAD_TOP + (i / (tickCount - 1)) * chartH;
      return { value: Math.round(val), y };
    });

    return {
      linePath: pts.length < 2 ? "" : line,
      areaPath: area,
      points: pts.map((p, i) => ({ x: p[0], y: p[1], value: data[i].value, label: data[i].label })),
      yTicks: ticks,
      xLabels: data.map((d, i) => ({ x: toXY(i, d.value)[0], label: d.label })),
    };
  }, [data]);

  return (
    <section className="chart-panel">
      <div className="panel-header">
        <h2>Nodularity Over Time</h2>
        <div className="chart-range">
          {["7D", "30D"].map((r) => (
            <button
              key={r}
              type="button"
              className={"range-btn" + (range === r ? " active" : "")}
              onClick={() => onRangeChange?.(r)}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      <div className="chart-container">
        {data.length === 0 ? (
          <div className="chart-empty">No inspections in this range yet.</div>
        ) : (
          <>
            <svg
              className="nodularity-chart"
              viewBox={`0 0 ${VB_W} ${VB_H}`}
              preserveAspectRatio="none"
            >
              {yTicks.map((t) => (
                <line
                  key={t.value}
                  className="nodularity-chart__grid"
                  x1={PAD_X}
                  x2={VB_W - PAD_X}
                  y1={t.y}
                  y2={t.y}
                  strokeDasharray="4 4"
                />
              ))}

              <defs>
                <linearGradient id="chartGradient" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0%" className="nodularity-chart__area-stop-top" />
                  <stop offset="100%" className="nodularity-chart__area-stop-bottom" />
                </linearGradient>
              </defs>

              <path d={areaPath} fill="url(#chartGradient)" />
              <path
                d={linePath}
                className="nodularity-chart__line"
                fill="none"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />

              {points.map((p, i) => (
                <circle
                  key={i}
                  className="nodularity-chart__dot"
                  cx={p.x}
                  cy={p.y}
                  r="3"
                  strokeWidth="1.5"
                >
                  <title>{`${p.label}: ${p.value}%`}</title>
                </circle>
              ))}
            </svg>

            <div className="chart-labels">
              {yTicks.map((t) => (
                <span key={t.value}>{t.value}%</span>
              ))}
            </div>
          </>
        )}
      </div>
    </section>
  );
}