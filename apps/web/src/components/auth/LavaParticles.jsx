import { useMemo } from 'react';
import './LavaParticles.css';

/**
 * Generates floating particle effects that flow from the lava animation
 * toward the login form, creating a cohesive visual connection.
 */
export default function LavaParticles() {
  const particles = useMemo(() => {
    return Array.from({ length: 15 }).map((_, i) => ({
      id: i,
      size: Math.random() * 8 + 3,
      duration: Math.random() * 3 + 4,
      delay: Math.random() * 2,
      startX: Math.random() * 20 + 40,
      endX: Math.random() * 30 + 70,
    }));
  }, []);

  return (
    <div className="lava-particles" aria-hidden="true">
      {particles.map((p) => (
        <div
          key={p.id}
          className="lava-particles__item"
          style={{
            '--size': `${p.size}px`,
            '--duration': `${p.duration}s`,
            '--delay': `${p.delay}s`,
            '--start-x': `${p.startX}%`,
            '--end-x': `${p.endX}%`,
          }}
        />
      ))}
    </div>
  );
}
