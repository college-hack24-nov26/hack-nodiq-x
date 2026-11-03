import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import './ProductShowcase.css';
import SectionHeading from '../common/SectionHeading';

const TABS = [
  { key: 'analyze', label: 'Analyze', hint: 'Microstructure image with detections' },
  { key: 'understand', label: 'Understand', hint: 'Results dashboard' },
  { key: 'verify', label: 'Verify', hint: 'Human review interface' },
];

const FLAGGED_INDICES = [4, 13, 19];
const SCALE_MICRONS_PER_PX = 1.20; // 1 px in SVG = 1.20 μm in sample

// Generate initial particles with metallurgical properties
function createInitialParticles() {
  return Array.from({ length: 22 }).map((_, i) => {
    const isFlagged = FLAGGED_INDICES.includes(i);
    const radius = 6 + (i % 4) * 2.2; // px
    const dMaxUm = +(radius * 2 * SCALE_MICRONS_PER_PX).toFixed(1);
    // ISO 945-4:2019 roundness: spheroidal >= 0.60, irregular < 0.60
    const roundness = isFlagged
      ? +(0.38 + ((i * 3) % 15) * 0.01).toFixed(2) // 0.38 - 0.52
      : +(0.78 + ((i * 7) % 18) * 0.01).toFixed(2); // 0.78 - 0.95
    // Area calculated via ISO 945 formula: R = 4A / (pi * d_max^2) => A = R * pi * d_max^2 / 4
    const areaUm2 = +(roundness * Math.PI * Math.pow(dMaxUm, 2) / 4).toFixed(1);
    
    // ISO 945 classification form
    let form = 'Form VI (Spheroidal)';
    let jisWeight = 1.0;
    if (isFlagged) {
      if (roundness < 0.42) {
        form = 'Form III (Degenerate Flake)';
        jisWeight = 0.3;
      } else {
        form = 'Form IV (Compacted/Vermicular)';
        jisWeight = 0.6;
      }
    } else if (roundness < 0.85) {
      form = 'Form V (Slightly Irregular)';
      jisWeight = 0.8;
    }

    return {
      id: `P-${String(i + 1).padStart(2, '0')}`,
      index: i,
      cx: 35 + (i * 41) % 430,
      cy: 35 + Math.floor(i / 5) * 48 + (i % 3) * 10,
      vx: (Math.sin(i * 1.8 + 0.5) * 0.35) + (i % 2 === 0 ? 0.2 : -0.2),
      vy: (Math.cos(i * 2.1 + 0.3) * 0.35) + (i % 3 === 0 ? 0.2 : -0.2),
      radius,
      dMaxUm,
      areaUm2,
      roundness,
      form,
      jisWeight,
      conf: isFlagged ? 58 + ((i * 4) % 10) : 84 + ((i * 7) % 15),
      isFlagged,
    };
  });
}

export default function ProductShowcase() {
  const [active, setActive] = useState('analyze');
  const [particles, setParticles] = useState(createInitialParticles);
  const [isStreaming, setIsStreaming] = useState(true);
  const [speed, setSpeed] = useState(1);
  const [isScanning, setIsScanning] = useState(false);
  const [isCaptured, setIsCaptured] = useState(false);
  const [selectedParticleId, setSelectedParticleId] = useState('P-05');
  const [formulaStandard, setFormulaStandard] = useState('iso945'); // 'iso945' | 'jis' | 'astm'
  const [reviewDecisions, setReviewDecisions] = useState({}); // { [id]: 'accepted' | 'rejected' }

  const animFrameRef = useRef(null);
  const scanTimerRef = useRef(null);

  // Smooth floating motion loop when streaming
  useEffect(() => {
    if (!isStreaming) return;

    let lastTime = performance.now();

    const loop = (currentTime) => {
      const dt = Math.min((currentTime - lastTime) / 16.6, 2.0);
      lastTime = currentTime;

      setParticles((prev) =>
        prev.map((p) => {
          let cx = p.cx + p.vx * speed * dt;
          let cy = p.cy + p.vy * speed * dt;
          let vx = p.vx;
          let vy = p.vy;

          // Boundary bounds (stay inside 500x280 coordinate plane with margins)
          const minX = 25;
          const maxX = 475;
          const minY = 30;
          const maxY = 250;

          if (cx < minX) {
            cx = minX;
            vx = Math.abs(vx);
          } else if (cx > maxX) {
            cx = maxX;
            vx = -Math.abs(vx);
          }

          if (cy < minY) {
            cy = minY;
            vy = Math.abs(vy);
          } else if (cy > maxY) {
            cy = maxY;
            vy = -Math.abs(vy);
          }

          return { ...p, cx, cy, vx, vy };
        })
      );

      animFrameRef.current = requestAnimationFrame(loop);
    };

    animFrameRef.current = requestAnimationFrame(loop);

    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [isStreaming, speed]);

  // Capture frame action: freezes animation and sweeps high-tech scanner
  const handleCapture = useCallback(() => {
    if (isScanning) return;
    setIsStreaming(false);
    setIsScanning(true);

    if (scanTimerRef.current) clearTimeout(scanTimerRef.current);

    scanTimerRef.current = setTimeout(() => {
      setIsScanning(false);
      setIsCaptured(true);
      setSelectedParticleId((prev) => prev || 'P-05');
    }, 750);
  }, [isScanning]);

  // Resume streaming / motion
  const handleResume = useCallback(() => {
    setIsScanning(false);
    setIsCaptured(false);
    setIsStreaming(true);
  }, []);

  // Re-seed new sample field
  const handleReseed = useCallback(() => {
    setParticles(createInitialParticles());
    setIsStreaming(true);
    setIsCaptured(false);
    setIsScanning(false);
    setSelectedParticleId('P-05');
  }, []);

  // Compute live nodularity statistics from the particles
  const stats = useMemo(() => {
    let totalArea = 0;
    let spheroidalArea = 0;
    let nonSpheroidalArea = 0;
    let jisWeightedArea = 0;
    let spheroidalCount = 0;
    let totalDMax = 0;

    particles.forEach((p) => {
      const area = p.areaUm2;
      totalArea += area;
      totalDMax += p.dMaxUm;

      // Check if user manually accepted a flagged particle in Verify tab
      const isOverriddenAccepted = reviewDecisions[p.id] === 'accepted';
      const isSpheroidal = p.roundness >= 0.60 || isOverriddenAccepted;

      if (isSpheroidal) {
        spheroidalArea += area;
        spheroidalCount += 1;
      } else {
        nonSpheroidalArea += area;
      }

      // JIS shape weighting
      const weight = isOverriddenAccepted ? 1.0 : p.jisWeight;
      jisWeightedArea += area * weight;
    });

    const totalCount = particles.length || 1;
    const isoNodularityPct = totalArea > 0 ? +((spheroidalArea / totalArea) * 100).toFixed(1) : 87.4;
    const jisNodularityPct = totalArea > 0 ? +((jisWeightedArea / totalArea) * 100).toFixed(1) : 90.5;
    const astmNodularityPct = +((spheroidalCount / totalCount) * 100).toFixed(1);
    const avgDiameterUm = +(totalDMax / totalCount).toFixed(1);

    return {
      totalCount,
      spheroidalCount,
      nonSpheroidalCount: totalCount - spheroidalCount,
      totalArea: Math.round(totalArea),
      spheroidalArea: Math.round(spheroidalArea),
      nonSpheroidalArea: Math.round(nonSpheroidalArea),
      isoNodularityPct,
      jisNodularityPct,
      astmNodularityPct,
      avgDiameterUm,
    };
  }, [particles, reviewDecisions]);

  // Selected particle dossier
  const selectedParticle = useMemo(() => {
    if (!selectedParticleId) return particles[4] || particles[0];
    return particles.find((p) => p.id === selectedParticleId) || particles[0];
  }, [particles, selectedParticleId]);

  // Dynamic metrics for the Understand tab
  const dynamicMetrics = useMemo(() => [
    {
      label: 'Nodularity',
      value: `${stats.isoNodularityPct}%`,
      desc: 'Area-weighted ISO 945-4 percentage calculated from current sample.',
      highlight: true,
    },
    {
      label: 'Nodule Count',
      value: `${stats.totalCount}`,
      desc: `${stats.spheroidalCount} spheroidal (Form V/VI) + ${stats.nonSpheroidalCount} irregular.`,
    },
    {
      label: 'Avg Diameter',
      value: `${stats.avgDiameterUm} μm`,
      desc: 'Calculated across maximum Feret diameters in calibrated pixels.',
    },
    {
      label: 'Graphite Area',
      value: `${(stats.totalArea).toLocaleString()} μm²`,
      desc: `Spheroidal graphite covers ${(stats.spheroidalArea).toLocaleString()} μm².`,
    },
    {
      label: 'Anomalies',
      value: `${stats.nonSpheroidalCount}`,
      desc: 'Particles with roundness R < 0.60 flagged for engineer review.',
      warning: stats.nonSpheroidalCount > 0,
    },
  ], [stats]);

  return (
    <section className="section showcase" id="product">
      <div className="container">
        <p className="eyebrow">Product</p>
        <SectionHeading text="See NODIQ-X in Action" accentFrom={2} />

        {/* Primary Tabs */}
        <div className="showcase__tabs">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              className={`showcase__tab ${active === t.key ? 'showcase__tab--active' : ''}`}
              onClick={() => setActive(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="showcase__panel">
          <AnimatePresence mode="wait">
            {active === 'analyze' && (
              <motion.div key="analyze" {...panelMotion} className="showcase__content">
                {/* Micrograph Viewport Header / Controls */}
                <div className="showcase__toolbar">
                  <div className="showcase__status-cluster">
                    <span
                      className={`showcase__stream-pill ${
                        isStreaming
                          ? 'showcase__stream-pill--live'
                          : isScanning
                          ? 'showcase__stream-pill--scanning'
                          : 'showcase__stream-pill--captured'
                      }`}
                    >
                      <span className="showcase__pulse-dot" />
                      {isStreaming
                        ? 'LIVE OPTICAL FEED · STAGE DRIFT ACTIVE'
                        : isScanning
                        ? 'LASER SCANNING & CALIBRATING...'
                        : 'FRAME CAPTURED & CALIBRATED (100× MAG)'}
                    </span>

                    <span className="showcase__telemetry mono">
                      1.20 μm/px · {stats.totalCount} PARTICLES · ISO 945-4:2019
                    </span>
                  </div>

                  <div className="showcase__actions">
                    {isStreaming ? (
                      <button
                        type="button"
                        className="showcase__btn showcase__btn--primary"
                        onClick={handleCapture}
                        title="Freeze current optical field and calculate metallurgical nodularity"
                      >
                        <svg className="showcase__btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <circle cx="12" cy="12" r="3" />
                          <path d="M4 8V6a2 2 0 0 1 2-2h2 M16 4h2a2 2 0 0 1 2 2v2 M20 16v2a2 2 0 0 1-2 2h-2 M8 20H6a2 2 0 0 1-2-2v-2" />
                        </svg>
                        Capture &amp; Calculate
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="showcase__btn showcase__btn--primary"
                        onClick={handleResume}
                        title="Resume continuous optical stage motion"
                      >
                        <svg className="showcase__btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <polygon points="5 3 19 12 5 21 5 3" />
                        </svg>
                        Resume Live Motion
                      </button>
                    )}

                    <button
                      type="button"
                      className={`showcase__btn showcase__btn--ghost ${speed === 2 ? 'showcase__btn--active' : ''}`}
                      onClick={() => setSpeed((s) => (s === 1 ? 2 : 1))}
                      title="Toggle simulated stage drift velocity"
                    >
                      {speed}× Speed
                    </button>

                    <button
                      type="button"
                      className="showcase__btn showcase__btn--ghost"
                      onClick={handleReseed}
                      title="Re-seed particle positions"
                    >
                      ↺ New Field
                    </button>
                  </div>
                </div>

                {/* Micrograph Canvas with Moving / Captured Nodules */}
                <div className={`showcase__image-container ${isScanning ? 'showcase__image-container--scanning' : ''}`}>
                  <svg
                    viewBox="0 0 500 280"
                    role="img"
                    aria-labelledby="showcase-caption"
                    className="showcase__micrograph-svg"
                  >
                    <defs>
                      <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
                        <path d="M 40 0 L 0 0 0 40" fill="none" stroke="rgba(255,122,24,0.06)" strokeWidth="0.5" />
                      </pattern>
                      <pattern id="fineGrid" width="10" height="10" patternUnits="userSpaceOnUse">
                        <path d="M 10 0 L 0 0 0 10" fill="none" stroke="rgba(255,255,255,0.02)" strokeWidth="0.3" />
                      </pattern>
                      <linearGradient id="bgGradient" x1="0%" y1="0%" x2="100%" y2="100%">
                        <stop offset="0%" style={{ stopColor: '#1a2023', stopOpacity: 1 }} />
                        <stop offset="100%" style={{ stopColor: '#13181a', stopOpacity: 1 }} />
                      </linearGradient>
                      <radialGradient id="noduleGlow" cx="50%" cy="50%" r="50%">
                        <stop offset="0%" stopColor="#FF7A18" stopOpacity="0.25" />
                        <stop offset="100%" stopColor="#FF7A18" stopOpacity="0" />
                      </radialGradient>
                      <radialGradient id="flaggedGlow" cx="50%" cy="50%" r="50%">
                        <stop offset="0%" stopColor="#EF5350" stopOpacity="0.35" />
                        <stop offset="100%" stopColor="#EF5350" stopOpacity="0" />
                      </radialGradient>
                    </defs>

                    {/* Background Grids */}
                    <rect width="500" height="280" fill="url(#bgGradient)" />
                    <rect width="500" height="280" fill="url(#fineGrid)" />
                    <rect width="500" height="280" fill="url(#grid)" />

                    {/* Measurement Scale Bar (100 μm) */}
                    <g opacity="0.6">
                      <line x1="24" y1="22" x2="107" y2="22" stroke="#FF7A18" strokeWidth="1.2" />
                      <line x1="24" y1="17" x2="24" y2="27" stroke="#FF7A18" strokeWidth="1.2" />
                      <line x1="107" y1="17" x2="107" y2="27" stroke="#FF7A18" strokeWidth="1.2" />
                      <text x="65" y="36" fontSize="9.5" fill="#F2B84B" textAnchor="middle" fontFamily="inherit" fontWeight="600">
                        100 μm
                      </text>
                    </g>

                    {/* Calibrated Axis Labels */}
                    <text x="250" y="272" fontSize="9" fill="#7E898E" textAnchor="middle" fontFamily="inherit">
                      Position across sample — X (μm)
                    </text>
                    <text
                      x="12"
                      y="140"
                      fontSize="9"
                      fill="#7E898E"
                      textAnchor="middle"
                      fontFamily="inherit"
                      transform="rotate(-90 12 140)"
                    >
                      Position — Y (μm)
                    </text>

                    {/* Live Motion Vectors / Velocity Trails when streaming */}
                    {isStreaming && (
                      <g opacity="0.45" stroke="#FF7A18" strokeWidth="0.8" strokeDasharray="1.5 2">
                        {particles.map((p) => (
                          <line
                            key={`trail-${p.id}`}
                            x1={p.cx - p.vx * 12}
                            y1={p.cy - p.vy * 12}
                            x2={p.cx}
                            y2={p.cy}
                          />
                        ))}
                      </g>
                    )}

                    {/* Detected Graphite Nodules */}
                    {particles.map((p) => {
                      const isSelected = selectedParticle.id === p.id;
                      const isFlagged = p.isFlagged;
                      const isOverriddenAccepted = reviewDecisions[p.id] === 'accepted';
                      const strokeColor = isFlagged && !isOverriddenAccepted
                        ? 'var(--color-error, #EF5350)'
                        : p.conf > 80
                        ? '#FF7A18'
                        : '#F2B84B';

                      return (
                        <g
                          key={p.id}
                          className={`showcase__nodule-group ${isSelected ? 'showcase__nodule-group--selected' : ''}`}
                          onClick={() => setSelectedParticleId(p.id)}
                          onMouseEnter={() => setSelectedParticleId(p.id)}
                          style={{ cursor: 'pointer' }}
                        >
                          {/* Generous transparent hit target */}
                          <circle
                            cx={p.cx}
                            cy={p.cy}
                            r={Math.max(p.radius + 8, 14)}
                            fill="transparent"
                          />

                          {/* Radial Glow Halo */}
                          <circle
                            cx={p.cx}
                            cy={p.cy}
                            r={p.radius * 2.2}
                            fill={isFlagged ? 'url(#flaggedGlow)' : 'url(#noduleGlow)'}
                            opacity={isSelected ? 0.9 : 0.4}
                          />

                          {/* Inner Graphite Core */}
                          <circle
                            cx={p.cx}
                            cy={p.cy}
                            r={p.radius}
                            fill={
                              isFlagged && !isOverriddenAccepted
                                ? 'rgba(239, 83, 80, 0.15)'
                                : 'rgba(255, 122, 24, 0.12)'
                            }
                            stroke={strokeColor}
                            strokeWidth={isSelected ? 2.0 : 1.3}
                          />

                          {/* Concentric boundary ring */}
                          <circle
                            cx={p.cx}
                            cy={p.cy}
                            r={p.radius + 2.2}
                            fill="none"
                            stroke={strokeColor}
                            strokeWidth="0.75"
                            opacity={0.5}
                          />

                          {/* Review Ring for Flagged Nodules */}
                          {isFlagged && !isOverriddenAccepted && (
                            <circle
                              cx={p.cx}
                              cy={p.cy}
                              r={p.radius + 5.5}
                              fill="none"
                              stroke="var(--color-error, #EF5350)"
                              strokeWidth="1.6"
                              strokeDasharray="3 3"
                            >
                              <animateTransform
                                attributeName="transform"
                                type="rotate"
                                from={`0 ${p.cx} ${p.cy}`}
                                to={`360 ${p.cx} ${p.cy}`}
                                dur="14s"
                                repeatCount="indefinite"
                              />
                            </circle>
                          )}

                          {/* Captured Target Reticle & Label */}
                          {(isCaptured || isSelected) && (
                            <g>
                              {/* Corner target reticles */}
                              <path
                                d={`
                                  M ${p.cx - p.radius - 4} ${p.cy - p.radius - 1} 
                                  v -3 h 3 
                                  M ${p.cx + p.radius + 4} ${p.cy - p.radius - 1} 
                                  v -3 h -3 
                                  M ${p.cx - p.radius - 4} ${p.cy + p.radius + 1} 
                                  v 3 h 3 
                                  M ${p.cx + p.radius + 4} ${p.cy + p.radius + 1} 
                                  v 3 h -3
                                `}
                                stroke={isSelected ? '#3BA5FF' : strokeColor}
                                strokeWidth="1.2"
                                fill="none"
                              />

                              {/* Micro ID Tag */}
                              <rect
                                x={p.cx - 14}
                                y={p.cy - p.radius - 13}
                                width="28"
                                height="10"
                                rx="2"
                                fill="rgba(16, 20, 22, 0.88)"
                                stroke={isSelected ? '#3BA5FF' : 'rgba(255, 122, 24, 0.3)'}
                                strokeWidth="0.6"
                              />
                              <text
                                x={p.cx}
                                y={p.cy - p.radius - 5}
                                fontSize="7.5"
                                fill={isSelected ? '#3BA5FF' : '#E8ECEE'}
                                textAnchor="middle"
                                fontFamily="inherit"
                                fontWeight="600"
                              >
                                {p.id}
                              </text>
                            </g>
                          )}
                        </g>
                      );
                    })}

                    {/* High-Tech Laser Scan Beam during capture */}
                    {isScanning && (
                      <g className="showcase__laser-beam-group">
                        <line
                          x1="0"
                          y1="0"
                          x2="0"
                          y2="280"
                          stroke="#3BA5FF"
                          strokeWidth="2.5"
                          opacity="0.95"
                        >
                          <animate
                            attributeName="x1"
                            from="0"
                            to="500"
                            dur="0.75s"
                            fill="freeze"
                          />
                          <animate
                            attributeName="x2"
                            from="0"
                            to="500"
                            dur="0.75s"
                            fill="freeze"
                          />
                        </line>
                      </g>
                    )}

                    {/* Legend Overlay */}
                    <g opacity="0.85">
                      <rect
                        x="320"
                        y="18"
                        width="168"
                        height="78"
                        fill="rgba(16, 20, 22, 0.88)"
                        stroke="rgba(255, 122, 24, 0.25)"
                        strokeWidth="1"
                        rx="5"
                      />
                      <circle cx="334" cy="32" r="4" fill="none" stroke="#FF7A18" strokeWidth="1.3" />
                      <text x="348" y="36" fontSize="10.5" fill="#E8ECEE" fontFamily="inherit">
                        High Conf (R ≥ 0.80)
                      </text>

                      <circle cx="334" cy="52" r="4" fill="none" stroke="#F2B84B" strokeWidth="1.3" />
                      <text x="348" y="56" fontSize="10.5" fill="#E8ECEE" fontFamily="inherit">
                        Medium Conf (0.60–0.80)
                      </text>

                      <circle cx="334" cy="72" r="4" fill="none" stroke="#EF5350" strokeWidth="1.4" strokeDasharray="2.4 2" />
                      <text x="348" y="76" fontSize="10.5" fill="#E8ECEE" fontFamily="inherit">
                        Flagged (R &lt; 0.60)
                      </text>
                    </g>
                  </svg>
                </div>

                {/* Subtitle / Legend */}
                <div className="showcase__legend" aria-hidden="true">
                  <span className="showcase__legend-item">
                    <svg viewBox="0 0 12 12">
                      <circle cx="6" cy="6" r="3" fill="none" stroke="#FF7A18" strokeWidth="1.2" />
                    </svg>
                    Circle diameter = Feret d_max
                  </span>
                  <span className="showcase__legend-item">
                    <svg viewBox="0 0 12 12">
                      <circle cx="6" cy="6" r="4" fill="none" stroke="#EF5350" strokeWidth="1.2" strokeDasharray="2 1.6" />
                    </svg>
                    Dashed ring = Flagged for review (R &lt; 0.60)
                  </span>
                  <span className="showcase__legend-item showcase__legend-item--tip">
                    <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.2">
                      <circle cx="6" cy="6" r="5" />
                      <line x1="6" y1="5" x2="6" y2="8" />
                      <circle cx="6" cy="3.5" r="0.5" fill="currentColor" />
                    </svg>
                    Click &ldquo;Capture &amp; Calculate&rdquo; to lock current optical field and evaluate formula
                  </span>
                </div>

                {/* Real-time Status Caption */}
                <p className="showcase__caption mono" id="showcase-caption">
                  {isStreaming ? (
                    <>
                      <span className="showcase__status-dot--live" /> Live Stage: {stats.totalCount} detections in field ·{' '}
                      {stats.nonSpheroidalCount} flagged (R &lt; 0.60) · Press &ldquo;Capture &amp; Calculate&rdquo; to lock frame
                    </>
                  ) : (
                    <>
                      <span className="showcase__status-dot--captured" /> Snapshot locked at T=0.00s · {stats.totalCount} particles evaluated · ISO Nodularity: <strong>{stats.isoNodularityPct}%</strong>
                    </>
                  )}
                </p>

                {/* ============================================================== */}
                {/* METALLURGICAL NODULARITY FORMULA ENGINE SECTION */}
                {/* ============================================================== */}
                <div className="showcase__formula-section">
                  <div className="formula__header">
                    <div className="formula__title-group">
                      <div className="formula__badge mono">METALLURGICAL ENGINE</div>
                      <h3 className="formula__heading">
                        Nodularity Formula &amp; Quantitative Derivation
                      </h3>
                      <p className="formula__subtext">
                        Dynamic computation directly evaluated from the captured graphite particles.
                      </p>
                    </div>

                    {/* Standard Switcher */}
                    <div className="formula__standards-tabs" role="tablist">
                      <button
                        type="button"
                        className={`formula__std-tab ${formulaStandard === 'iso945' ? 'formula__std-tab--active' : ''}`}
                        onClick={() => setFormulaStandard('iso945')}
                        title="ISO 945-4:2019 Area-Weighted Standard (Foundry Default)"
                      >
                        ISO 945-4:2019 (Area-Weighted)
                      </button>
                      <button
                        type="button"
                        className={`formula__std-tab ${formulaStandard === 'jis' ? 'formula__std-tab--active' : ''}`}
                        onClick={() => setFormulaStandard('jis')}
                        title="JIS G5502:2022 Shape-Factor Weighted Method"
                      >
                        JIS G5502 (Weighted)
                      </button>
                      <button
                        type="button"
                        className={`formula__std-tab ${formulaStandard === 'astm' ? 'formula__std-tab--active' : ''}`}
                        onClick={() => setFormulaStandard('astm')}
                        title="ASTM A247 Count-Based Standard"
                      >
                        ASTM A247 (Count-Based)
                      </button>
                    </div>
                  </div>

                  {/* Primary Mathematical Formula Card */}
                  <div className="formula__card">
                    <div className="formula__top-bar">
                      <span className="formula__card-label mono">
                        {formulaStandard === 'iso945' && 'STANDARD: ISO 945-4:2019 (CLAUSE 3.4)'}
                        {formulaStandard === 'jis' && 'STANDARD: JIS G5502:2022 (SHAPE FACTOR CONVENTION)'}
                        {formulaStandard === 'astm' && 'STANDARD: ASTM A247 / E2567 (PARTICLE RATIO)'}
                      </span>
                      <span className="formula__compliance-tag mono">
                        QUALIFIED FOR ASTM A536 / EN-GJS-400
                      </span>
                    </div>

                    {/* Formula Rendered with Math Markup */}
                    <div className="formula__equation-container">
                      {formulaStandard === 'iso945' && (
                        <div className="formula__equation-block">
                          <div className="formula__equation-math">
                            <span className="math__var">Nodularity</span>
                            <span className="math__unit">(%)</span>
                            <span className="math__eq">=</span>
                            <div className="math__fraction">
                              <span className="math__num">
                                &sum; Area<sub>spheroidal</sub> (R &ge; 0.60)
                              </span>
                              <span className="math__denom">
                                &sum; Area<sub>total graphite</sub>
                              </span>
                            </div>
                            <span className="math__op">&times;</span>
                            <span className="math__num">100%</span>
                          </div>

                          <div className="formula__arrow">&rarr;</div>

                          {/* Numerical Substitution */}
                          <div className="formula__substitution-math">
                            <span className="math__eq">=</span>
                            <div className="math__fraction">
                              <span className="math__num math__num--highlight">
                                {stats.spheroidalArea.toLocaleString()} &mu;m&sup2;
                              </span>
                              <span className="math__denom math__denom--highlight">
                                {stats.totalArea.toLocaleString()} &mu;m&sup2;
                              </span>
                            </div>
                            <span className="math__op">&times;</span>
                            <span className="math__num">100%</span>
                            <span className="math__eq">=</span>
                            <span className="math__result mono">{stats.isoNodularityPct}%</span>
                          </div>
                        </div>
                      )}

                      {formulaStandard === 'jis' && (
                        <div className="formula__equation-block">
                          <div className="formula__equation-math">
                            <span className="math__var">Nodularity<sub>JIS</sub></span>
                            <span className="math__unit">(%)</span>
                            <span className="math__eq">=</span>
                            <div className="math__fraction">
                              <span className="math__num">
                                &sum; (w<sub>i</sub> &times; Area<sub>i</sub>)
                              </span>
                              <span className="math__denom">
                                &sum; Area<sub>total</sub>
                              </span>
                            </div>
                            <span className="math__op">&times;</span>
                            <span className="math__num">100%</span>
                          </div>

                          <div className="formula__arrow">&rarr;</div>

                          <div className="formula__substitution-math">
                            <span className="math__eq">=</span>
                            <div className="math__fraction">
                              <span className="math__num math__num--highlight">
                                &sum; (w<sub>VI</sub>:1.0, w<sub>V</sub>:0.8, w<sub>IV</sub>:0.6)
                              </span>
                              <span className="math__denom math__denom--highlight">
                                {stats.totalArea.toLocaleString()} &mu;m&sup2;
                              </span>
                            </div>
                            <span className="math__op">&times;</span>
                            <span className="math__num">100%</span>
                            <span className="math__eq">=</span>
                            <span className="math__result mono">{stats.jisNodularityPct}%</span>
                          </div>
                        </div>
                      )}

                      {formulaStandard === 'astm' && (
                        <div className="formula__equation-block">
                          <div className="formula__equation-math">
                            <span className="math__var">Nodularity<sub>ASTM</sub></span>
                            <span className="math__unit">(%)</span>
                            <span className="math__eq">=</span>
                            <div className="math__fraction">
                              <span className="math__num">
                                N<sub>spheroidal</sub> (Form V &amp; VI)
                              </span>
                              <span className="math__denom">
                                N<sub>total graphite</sub>
                              </span>
                            </div>
                            <span className="math__op">&times;</span>
                            <span className="math__num">100%</span>
                          </div>

                          <div className="formula__arrow">&rarr;</div>

                          <div className="formula__substitution-math">
                            <span className="math__eq">=</span>
                            <div className="math__fraction">
                              <span className="math__num math__num--highlight">
                                {stats.spheroidalCount} particles
                              </span>
                              <span className="math__denom math__denom--highlight">
                                {stats.totalCount} particles
                              </span>
                            </div>
                            <span className="math__op">&times;</span>
                            <span className="math__num">100%</span>
                            <span className="math__eq">=</span>
                            <span className="math__result mono">{stats.astmNodularityPct}%</span>
                          </div>
                        </div>
                      )}
                    </div>

                    {/* Result Rating Banner */}
                    <div className="formula__verdict-strip">
                      <div className="formula__verdict-item">
                        <span className="formula__verdict-label mono">FOUNDRY STATUS</span>
                        <span className="formula__verdict-value formula__verdict-value--pass">
                          ✓ ACCEPTED · DUCTILE IRON GRADE A
                        </span>
                      </div>
                      <div className="formula__verdict-item">
                        <span className="formula__verdict-label mono">SPECIFICATION THRESHOLD</span>
                        <span className="formula__verdict-value">
                          &ge; 80.0% required for automotive/wind castings
                        </span>
                      </div>
                      <div className="formula__verdict-item">
                        <span className="formula__verdict-label mono">FRAME INTEGRITY</span>
                        <span className="formula__verdict-value">
                          {isStreaming ? 'Live Tracking (Dynamic)' : 'Frozen Calibration Verified'}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              </motion.div>
            )}

            {/* Understand Tab (Metrics Dashboard synchronized with capture) */}
            {active === 'understand' && (
              <motion.div key="understand" {...panelMotion} className="showcase__content showcase__content--dash">
                {dynamicMetrics.map((m, i) => (
                  <motion.div
                    key={m.label}
                    className={`showcase__metric ${m.highlight ? 'showcase__metric--highlight' : ''}`}
                    initial={{ opacity: 0, y: 14 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.08, duration: 0.4 }}
                  >
                    <span className="showcase__metric-label mono">{m.label}</span>
                    <span
                      className={`showcase__metric-value mono ${
                        m.warning ? 'showcase__metric-value--warning' : ''
                      }`}
                    >
                      {m.value}
                    </span>
                    <span className="showcase__metric-desc">{m.desc}</span>
                  </motion.div>
                ))}
              </motion.div>
            )}

            {/* Verify Tab (Human Review Interface) */}
            {active === 'verify' && (
              <motion.div key="verify" {...panelMotion} className="showcase__content showcase__content--verify">
                <div className="verify__header-note">
                  <span className="mono">HUMAN-IN-THE-LOOP QUALITY VERIFICATION</span>
                  <p>
                    Review detected particles flagged for geometric irregularities or confidence thresholds. Overriding decisions recalculates ISO 945-4 nodularity in real time.
                  </p>
                </div>

                {particles
                  .filter((p) => p.isFlagged)
                  .map((p) => {
                    const status = reviewDecisions[p.id];
                    return (
                      <div key={p.id} className="verify__row">
                        <span className="mono verify__particle-id">Detection #{p.id}</span>
                        <span className="verify__conf verify__conf--low mono">
                          Conf {p.conf}% · R = {p.roundness} ({p.form})
                        </span>
                        <span className="verify__diameter mono">{p.dMaxUm} μm · {p.areaUm2} μm²</span>
                        <div className="verify__actions">
                          <button
                            type="button"
                            className={`verify__accept ${status === 'accepted' ? 'verify__btn--chosen' : ''}`}
                            onClick={() =>
                              setReviewDecisions((prev) => ({ ...prev, [p.id]: 'accepted' }))
                            }
                          >
                            {status === 'accepted' ? '✓ Accepted' : 'Accept'}
                          </button>
                          <button
                            type="button"
                            className={`verify__reject ${status === 'rejected' ? 'verify__btn--chosen' : ''}`}
                            onClick={() =>
                              setReviewDecisions((prev) => ({ ...prev, [p.id]: 'rejected' }))
                            }
                          >
                            {status === 'rejected' ? '✗ Rejected' : 'Reject'}
                          </button>
                        </div>
                      </div>
                    );
                  })}

                <div className="verify__footer mono">
                  Current Recalculated Nodularity:{' '}
                  <strong className="verify__recalculated-stat">{stats.isoNodularityPct}%</strong>{' '}
                  (Standard: ISO 945-4:2019)
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </section>
  );
}

const panelMotion = {
  initial: { opacity: 0, y: 10 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -10 },
  transition: { duration: 0.35, ease: [0.16, 1, 0.3, 1] },
};
