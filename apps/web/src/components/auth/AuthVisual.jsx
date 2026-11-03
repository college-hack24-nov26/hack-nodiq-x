import { motion } from 'framer-motion';
import { useEffect, useRef } from 'react';
import MicrostructureField from '../common/MicrostructureField';
import './AuthVisual.css';

export default function AuthVisual({ hideContent = false }) {
  const videoRef = useRef(null);

  // Some browsers block the autoplay attribute (tab restore, power saver,
  // autoplay policies). Retry playback explicitly once the video can play.
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const tryPlay = () => {
      video.play().catch(() => {
        /* Retry on first user interaction if still blocked. */
        const resume = () => {
          video.play().catch(() => {});
          window.removeEventListener('pointerdown', resume);
          window.removeEventListener('keydown', resume);
        };
        window.addEventListener('pointerdown', resume, { once: true });
        window.addEventListener('keydown', resume, { once: true });
      });
    };

    if (video.readyState >= 3) {
      tryPlay();
    } else {
      video.addEventListener('canplay', tryPlay, { once: true });
    }

    return () => video.removeEventListener('canplay', tryPlay);
  }, []);

  return (
    <div className="auth-visual">
      <video
        ref={videoRef}
        className="auth-visual__video"
        autoPlay
        muted
        loop
        playsInline
        preload="auto"
        aria-hidden="true"
      >
        <source src="/videos/nodiq-login-loop-480p-backup.mp4" type="video/mp4" />
        {/* HD master: secondary fallback (and directly linkable at
            /videos/nodiq-login-loop.mp4); the 480p stays first so mobile
            loads fast. */}
        <source src="/videos/nodiq-login-loop.mp4" type="video/mp4" />
      </video>

      <div className="auth-visual__overlay" />

      <div className="auth-visual__field">
        <MicrostructureField density={60} seed={23} highlightIndices={[5, 18, 27, 44]} />
      </div>

      {!hideContent && (
        <div className="auth-visual__content">
        <motion.a
          href="/"
          className="auth-visual__logo"
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
        >
          <span className="auth-visual__mark" /><span>NODIQ<span className="auth-visual__accent">-X</span></span>
        </motion.a>

        <motion.h1
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.15, ease: [0.16, 1, 0.3, 1] }}
        >
          Precision analysis, ready when you are.
        </motion.h1>

        <motion.p
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.25, ease: [0.16, 1, 0.3, 1] }}
        >
          Sign in to upload samples, review AI-assisted detections, and generate
          engineering-ready reports.
        </motion.p>
        </div>
      )}
    </div>
  );
}
