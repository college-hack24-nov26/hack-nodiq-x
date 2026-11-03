import { motion } from 'framer-motion';
import Reveal from '../animations/Reveal';
import SlideUp from '../animations/SlideUp';
import './CopilotPreview.css';
import SectionHeading from '../common/SectionHeading';

const CONTEXT = [
  { label: 'Sample ID', value: 'SAMPLE_07A' },
  { label: 'Nodularity', value: '87.4%' },
  { label: 'Nodule Count', value: '142' },
  { label: 'Confidence', value: '84.9%' },
  { label: 'Anomalies', value: '3' },
];

const SUGGESTED = [
  'Why is my nodularity low?',
  'Explain this analysis.',
  'What anomalies should I review?',
  'Compare this sample with the reference.',
  'What should I verify?',
];

export default function CopilotPreview() {
  return (
    <section className="section copilot">
      <div className="container">
        <p className="eyebrow">NODIQ Copilot</p>
        <SectionHeading text="Your Analysis Has an AI Copilot" accentFrom={2} />

        <div className="copilot__layout">
          <motion.div
            className="copilot__chat"
            initial={{ opacity: 0, y: 24 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.2 }}
            transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
          >
            <div className="copilot__chat-header">
              <span className="copilot__dot" />
              <span className="copilot__chip-label">NODIQ COPILOT</span>
            </div>

            <div className="copilot__messages">
              <div className="copilot__msg copilot__msg--user">
                <span className="copilot__msg-label mono">ENGINEER</span>
                <p>Why is my nodularity lower than the reference?</p>
              </div>
              <motion.div
                className="copilot__msg copilot__msg--ai"
                initial={{ opacity: 0, y: 10 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: 0.35, duration: 0.5 }}
              >
                <span className="copilot__msg-label mono">NODIQ COPILOT</span>
                <p>
                  The sample shows a higher proportion of irregular morphology and several
                  low-confidence detections. Three regions may require manual verification.
                </p>
              </motion.div>
            </div>

            <div className="copilot__suggested">
              {SUGGESTED.map((s) => (
                <span key={s} className="copilot__chip">{s}</span>
              ))}
            </div>
          </motion.div>

          <Reveal className="copilot__context">
            {CONTEXT.map((c, i) => (
              <SlideUp key={c.label} index={i} staggerStep={0.07} className="copilot__context-row">
                <span className="copilot__context-label">{c.label}</span>
                <span className="mono copilot__context-value">{c.value}</span>
              </SlideUp>
            ))}
          </Reveal>
        </div>
      </div>
    </section>
  );
}
