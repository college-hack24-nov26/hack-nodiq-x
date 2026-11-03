import { useEffect, useRef, useState, useCallback } from 'react';
import './HeroAnalysis.css';

/**
 * HeroAnalysis — Cinematic Metallography Video Feed
 * Integrates high-definition metallurgical microstructure / 3D crystallography video
 * with interactive microscope HUD telemetry, calibration scale,
 * and live scanning status.
 */
export default function HeroAnalysis() {
  const videoRef = useRef(null);
  const [isPlaying, setIsPlaying] = useState(true);
  const [isLoaded, setIsLoaded] = useState(false);
  const [showStatus, setShowStatus] = useState(false);
  const statusTimer = useRef(null);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    video.muted = true;
    video.playsInline = true;

    const playPromise = video.play();
    if (playPromise !== undefined) {
      playPromise
        .then(() => setIsPlaying(true))
        .catch((err) => {
          console.warn('Microstructure video autoplay prevented by browser:', err);
          setIsPlaying(false);
        });
    }

    return () => {
      clearTimeout(statusTimer.current);
    };
  }, []);

  const togglePlay = useCallback((e) => {
    e?.stopPropagation();
    const video = videoRef.current;
    if (!video) return;

    if (video.paused) {
      video.play().then(() => setIsPlaying(true)).catch(() => {});
    } else {
      video.pause();
      setIsPlaying(false);
    }
    setShowStatus(true);
    clearTimeout(statusTimer.current);
    statusTimer.current = setTimeout(() => setShowStatus(false), 1200);
  }, []);

  return (
    <div
      className="ha__video-stage"
      onClick={togglePlay}
      onKeyDown={(e) => {
        if (e.key === ' ' || e.key === 'Enter') {
          e.preventDefault();
          togglePlay();
        }
      }}
      tabIndex={0}
      role="button"
      aria-label={isPlaying ? 'Pause analysis stream' : 'Resume analysis stream'}
      title="Click or press Space to pause / resume stream"
    >
      {/* 3D Metallurgical Microstructure & Crystallography Video */}
      <video
        ref={videoRef}
        poster="/video_poster.jpg"
        autoPlay
        loop
        muted
        playsInline
        preload="auto"
        className={`ha__video ${isLoaded ? 'ha__video--ready' : ''}`}
        onLoadedData={() => setIsLoaded(true)}
      >
        <source src="/gemini_generated_video_dbd66bea.mp4" type="video/mp4" />
        <source src="/microstructure_analysis.mp4" type="video/mp4" />
        Your browser does not support HTML5 video.
      </video>

      {/* Ambient Vignette & Subtle Optical Scanline Grid */}
      <div className="ha__vignette" />
      <div className="ha__scanlines" />

      {/* Metallurgical Microscope HUD Overlay */}
      <div className="ha__hud">
        {/* Top-left Scale Calibration Bar */}
        <div className="ha__hud-scalebar">
          <div className="ha__scale-rule">
            <span className="ha__scale-tick left" />
            <span className="ha__scale-bar" />
            <span className="ha__scale-tick right" />
          </div>
          <span className="ha__scale-text mono">100 μm</span>
        </div>

        {/* Corner Viewfinder Reticles */}
        <div className="ha__reticle ha__reticle--tl" />
        <div className="ha__reticle ha__reticle--tr" />
        <div className="ha__reticle ha__reticle--bl" />
        <div className="ha__reticle ha__reticle--br" />

        {/* Center Optical Crosshair */}
        <div className="ha__crosshair">
          <span className="ha__crosshair-x" />
          <span className="ha__crosshair-y" />
        </div>

        {/* Transient Pause / Play Feedback Indicator (stays visible when paused as click-to-resume prompt) */}
        <div className={`ha__play-status ${showStatus || !isPlaying ? 'ha__play-status--visible' : ''}`}>
          {isPlaying ? (
            <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
              <polygon points="5 3 19 12 5 21 5 3" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
              <polygon points="6 4 20 12 6 20 6 4" />
            </svg>
          )}
          <span className="mono">{isPlaying ? 'LIVE STREAM' : 'PAUSED · CLICK TO PLAY'}</span>
        </div>
      </div>
    </div>
  );
}
