import Reveal from '../animations/Reveal';
import SlideUp from '../animations/SlideUp';
import Card from '../common/Card';
import Icon from '../common/Icon';
import './TrustSection.css';
import SectionHeading from '../common/SectionHeading';

const ITEMS = [
  { title: 'Confidence Scores', desc: 'Every detection carries a transparent confidence value.', icon: 'confidence' },
  { title: 'Ground Truth Comparison', desc: 'Compare detections against verified references.', icon: 'comparison' },
  { title: 'Reference Library', desc: 'Draw on a maintained library of reference microstructures.', icon: 'reference' },
  { title: 'Human Verification', desc: 'Engineers can accept, reject, or correct any detection.', icon: 'humanVerification' },
  { title: 'Validation Metrics', desc: 'Track how detections hold up against review outcomes.', icon: 'metrics' },
  { title: 'Audit Trail', desc: 'Every correction and report is logged and traceable.', icon: 'audit' },
];

export default function TrustSection() {
  return (
    <section className="section trust" id="trust">
      <div className="container">
        <p className="eyebrow">Validation & Trust</p>
        <SectionHeading text="AI You Can Inspect. Results You Can Trust." accentFrom={2} />

        <Reveal className="trust__grid">
          {ITEMS.map((it, i) => (
            <SlideUp key={it.title} index={i} staggerStep={0.06}>
              <Card hoverable={false} className="trust__card">
                <Icon name={it.icon} size="md" />
                <h3>{it.title}</h3>
                <p>{it.desc}</p>
              </Card>
            </SlideUp>
          ))}
        </Reveal>
      </div>
    </section>
  );
}
