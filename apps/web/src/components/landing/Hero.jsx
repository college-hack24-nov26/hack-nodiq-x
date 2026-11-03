import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import SpecularButton from '../common/SpecularButton';
import MicrostructureField from '../common/MicrostructureField';
import Particles from '../animations/Particles';
import { useTheme } from '../../context/ThemeContext';
import HeroAnalysis from './HeroAnalysis';
import './Hero.css';

const TRUST = ['AI-Assisted', 'Confidence-Aware', 'Human-Verified'];

/**
 * Audit issue 14: the background-clip gradient on .hero__heading cuts across
 * the text block, splitting words mid-way ("Intelli|gence"). Wrapping each
 * word in its own span makes the gradient land on whole words instead.
 */
function GradientWords({ text }) {
  return text.split(' ').map((word, i) => (
    <span key={`${word}-${i}`} className="hero__word">{word}{" "}</span>
  ));
}

const easeOut = [0.16, 1, 0.3, 1];

export default function Hero() {
  const navigate = useNavigate();
  const { theme } = useTheme();
  const isLight = theme === 'light';

  return (
    <section className="hero" id="product-hero">
      <div className="hero__field">
        <Particles
          particleColors={
            isLight
              ? ['#ea580c', '#334155', '#64748b']
              : ['#ff7a18', '#ffd8a8', '#ffffff']
          }
          particleCount={220}
          particleSpread={8}
          speed={0.1}
          particleBaseSize={100}
          glow={isLight ? 0.35 : 0.55}
          twinkle={0.3}
          moveParticlesOnHover
          hoverEffect="parallax"
          lightMode={isLight}
        />
        <MicrostructureField density={54} seed={11} highlightIndices={[3, 14, 22, 31, 40]} />
      </div>

      <div className="container hero__inner">
        <div className="hero__copy">
          <motion.p
            className="eyebrow hero__eyebrow"
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, ease: easeOut }}
          >
            NODIQ-X · Metallographic Intelligence
          </motion.p>

          <motion.h1
            className="hero__heading"
            initial={{ opacity: 0, y: 22 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.08, ease: easeOut }}
          >
            <GradientWords text="AI-Powered Metallography Analysis" />
          </motion.h1>

          <motion.p
            className="hero__sub"
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.18, ease: easeOut }}
          >
            Detect, measure and classify microstructural features with intelligent image analysis.
          </motion.p>

          <motion.div
            className="hero__cta"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.3, ease: easeOut }}
          >
            <SpecularButton
              size="lg"
              radius={18}
              tint="#18181b"
              tintOpacity={1}
              textColor="#ffffff"
              lineColor="#f97316"
              baseColor="#ffffff"
              intensity={1}
              idleIntensity={0.35}
              shineSize={10}
              shineFade={34}
              thickness={1.2}
              glow={1}
              followMouse
              proximity={250}
              href="/login"
              onClick={(e) => {
                e.preventDefault();
                navigate('/login');
              }}
            >
              Get Started
            </SpecularButton>

            <SpecularButton
              size="lg"
              radius={18}
              tint="#18181b"
              tintOpacity={1}
              textColor="#ffffff"
              lineColor="#f97316"
              baseColor="#ffffff"
              intensity={1}
              idleIntensity={0.35}
              shineSize={10}
              shineFade={34}
              thickness={1.2}
              glow={1}
              followMouse
              proximity={250}
              href="#product"
              onClick={(e) => {
                e.preventDefault();
                document.getElementById('product')?.scrollIntoView({ behavior: 'smooth' });
              }}
            >
              Explore Analysis
            </SpecularButton>
          </motion.div>

          <motion.div
            className="hero__trust"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.6, delay: 0.42 }}
          >
            {TRUST.map((t) => (
              <span key={t} className="hero__trust-item">
                <span className="hero__trust-dot" /> {t}
              </span>
            ))}
          </motion.div>
        </div>

        <motion.div
          className="hero__visual"
          initial={{ opacity: 0, scale: 0.94, y: 20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.35, ease: easeOut }}
        >
          <div className="scope">
            <div className="scope__viewport">
              <HeroAnalysis />
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}
