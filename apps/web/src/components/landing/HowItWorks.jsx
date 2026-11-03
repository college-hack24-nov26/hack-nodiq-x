import { motion } from 'framer-motion';
import Reveal from '../animations/Reveal';
import './HowItWorks.css';
import SectionHeading from '../common/SectionHeading';

const STEPS = [
  { n: '01', title: 'Upload', desc: 'Upload a metallographic image.' },
  { n: '02', title: 'Quality Check', desc: 'Verify image quality before analysis.' },
  { n: '03', title: 'AI Analysis', desc: 'Detect nodules and analyze morphology.' },
  { n: '04', title: 'Review & Validate', desc: 'Inspect and correct AI detections.' },
  { n: '05', title: 'Report & Understand', desc: 'Generate reports and ask NODIQ Copilot.' },
];

const containerVariants = {
  hidden: {},
  show: {
    transition: {
      staggerChildren: 0.12,
      delayChildren: 0.2,
    },
  },
};

const stepVariants = {
  hidden: { 
    opacity: 0, 
    y: 30,
  },
  show: { 
    opacity: 1, 
    y: 0,
    transition: { 
      duration: 0.6, 
      ease: [0.16, 1, 0.3, 1] 
    } 
  },
};

export default function HowItWorks() {
  return (
    <section className="section how" id="how-it-works">
      <div className="container">
        <Reveal>
          <p className="eyebrow">Workflow</p>
        <SectionHeading text="From Image to Insight in 5 Steps" accentFrom={2} />
        </Reveal>

        <motion.div
          className="how__timeline"
          initial="hidden"
          whileInView="show"
          viewport={{ once: true, amount: 0.2 }}
          variants={containerVariants}
        >
          <motion.div
            className="how__line"
            initial={{ scaleX: 0 }}
            whileInView={{ scaleX: 1 }}
            viewport={{ once: true, amount: 0.15 }}
            transition={{ duration: 1.2, ease: [0.16, 1, 0.3, 1], delay: 0.2 }}
          />
          {STEPS.map((s, i) => (
            <motion.div
              key={s.n}
              className="how__step"
              variants={stepVariants}
            >
              <div className="how__marker-wrapper">
                <span className="how__marker mono">{s.n}</span>
                <motion.div 
                  className="how__marker-pulse"
                  initial={{ scale: 1, opacity: 1 }}
                  whileInView={{ scale: 1.5, opacity: 0 }}
                  transition={{ duration: 1.5, repeat: Infinity, delay: 0.2 + i * 0.12 }}
                  viewport={{ once: true }}
                />
              </div>
              <h3>{s.title}</h3>
              <p>{s.desc}</p>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}
