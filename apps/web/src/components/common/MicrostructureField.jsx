import { useMemo } from 'react';
import './MicrostructureField.css';

/**
 * Generates a deterministic-but-organic field of nodule-like circles,
 * evoking a metallographic micrograph. Used as low-opacity ambient
 * texture behind hero/auth content. Pure SVG + CSS, no external assets.
 */
export default function MicrostructureField({ density = 42, seed = 7, highlightIndices = [] }) {
  const nodules = useMemo(() => {
    let s = seed;
    const rand = () => {
      s = (s * 9301 + 49297) % 233280;
      return s / 233280;
    };
    return Array.from({ length: density }).map((_, i) => ({
      id: i,
      cx: rand() * 100,
      cy: rand() * 100,
      r: 0.6 + rand() * 1.8,
    }));
  }, [density, seed]);

  return (
    <svg className="microfield" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      {nodules.map((n) => {
        const isHighlight = highlightIndices.includes(n.id);
        return (
          <g key={n.id} className={`microfield__nodule anim-drift`} style={{ animationDelay: `${(n.id % 9) * 0.4}s` }}>
            <circle
              cx={n.cx}
              cy={n.cy}
              r={n.r}
              className={isHighlight ? 'microfield__circle--hl' : 'microfield__circle'}
            />
            {isHighlight && (
              <circle cx={n.cx} cy={n.cy} r={n.r + 1.6} className="microfield__ring" />
            )}
          </g>
        );
      })}
    </svg>
  );
}
