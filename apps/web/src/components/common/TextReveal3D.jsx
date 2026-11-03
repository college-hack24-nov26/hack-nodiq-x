import { useEffect, useRef } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import './TextReveal3D.css';

gsap.registerPlugin(ScrollTrigger);

export default function TextReveal3D({ text, className = '' }) {
  const containerRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chars = containerRef.current.querySelectorAll('.text-reveal__char');

    // Animate each character with 3D perspective
    gsap.to(chars, {
      scrollTrigger: {
        trigger: containerRef.current,
        start: 'top 80%',
        end: 'top 20%',
        scrub: 0.5,
        markers: false,
      },
      opacity: 1,
      y: 0,
      rotationX: 0,
      duration: 0.6,
      stagger: {
        amount: 0.5,
        from: 'start',
      },
      ease: 'power2.out',
    });

    return () => {
      ScrollTrigger.getAll().forEach(trigger => trigger.kill());
    };
  }, []);

  // Split text into characters
  const chars = text.split('').map((char, idx) => (
    <span
      key={idx}
      className="text-reveal__char"
      style={{
        opacity: 0,
        transform: 'translateY(20px) rotateX(90deg)',
      }}
    >
      {char}
    </span>
  ));

  return (
    <div ref={containerRef} className={`text-reveal ${className}`}>
      {chars}
    </div>
  );
}
