import Reveal from '../animations/Reveal';
import SlideUp from '../animations/SlideUp';
import Card from '../common/Card';
import Icon from '../common/Icon';
import './Features.css';
import SectionHeading from '../common/SectionHeading';

const FEATURES = [
  { title: 'AI Nodule Detection', desc: 'Detect nodules automatically.', icon: 'detection' },
  { title: 'Nodularity Analysis', desc: 'Calculate important structural measurements.', icon: 'analysis' },
  { title: 'Morphology Analysis', desc: 'Understand size, shape and distribution.', icon: 'morphology' },
  { title: 'Confidence-Aware Results', desc: 'Identify reliable and uncertain detections.', icon: 'confidence' },
  { title: 'Human Verification', desc: 'Add, remove and correct detections.', icon: 'verification' },
  { title: 'Batch Analytics', desc: 'Analyze multiple samples efficiently.', icon: 'batch' },
  { title: 'AI Copilot', desc: 'Ask questions about your analysis.', icon: 'copilot' },
  { title: 'Engineering Reports', desc: 'Generate professional reports.', icon: 'report' },
];

export default function Features() {
  return (
    <section className="section features" id="features">
      <div className="container">
        <p className="eyebrow">Capabilities</p>
        <SectionHeading text="Everything You Need for Intelligent Microstructure Analysis" accentFrom={2} />

        <Reveal className="features__grid">
          {FEATURES.map((f, i) => (
            <SlideUp key={f.title} index={i} staggerStep={0.06}>
              <Card className="features__card">
                <Icon name={f.icon} size="md" />
                <h3>{f.title}</h3>
                <p>{f.desc}</p>
              </Card>
            </SlideUp>
          ))}
        </Reveal>
      </div>
    </section>
  );
}
