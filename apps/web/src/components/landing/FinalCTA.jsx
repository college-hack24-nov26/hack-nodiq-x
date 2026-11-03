import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import SpecularButton from '../common/SpecularButton';
import './FinalCTA.css';

export default function FinalCTA() {
  const navigate = useNavigate();

  return (
    <section className="section final-cta">
      <div className="container">
        <motion.div
          className="final-cta__panel"
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
        >
          <div className="final-cta__grain" aria-hidden="true" />
          <h2>Turn Microstructure Images Into Engineering Insights</h2>
          <p>Start your analysis with NODIQ-X.</p>
          <SpecularButton
            size="lg"
            radius={18}
            lineColor="#f97316"
            baseColor="#94a3b8"
            intensity={1}
            idleIntensity={0.35}
            shineSize={12}
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
        </motion.div>
      </div>
    </section>
  );
}
