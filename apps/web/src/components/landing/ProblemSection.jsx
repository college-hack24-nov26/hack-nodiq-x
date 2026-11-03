import Reveal from '../animations/Reveal';
import SlideUp from '../animations/SlideUp';
import Card from '../common/Card';
import Icon from '../common/Icon';
import './ProblemSection.css';
import SectionHeading from '../common/SectionHeading';

const PROBLEMS = [
  { code: 'PT-01', title: 'Manual Analysis', desc: 'Time-consuming image inspection.', icon: 'manual' },
  { code: 'PT-02', title: 'Subjective Interpretation', desc: 'Results can depend on individual judgment.', icon: 'subjective' },
  { code: 'PT-03', title: 'Inconsistent Measurements', desc: 'Manual measurements can introduce variation.', icon: 'inconsistent' },
  { code: 'PT-04', title: 'Slow Reporting', desc: 'Analysis often requires additional reporting work.', icon: 'slow' },
];

export default function ProblemSection() {
  return (
    <section className="section problem">
      <div className="container">
        <p className="eyebrow">The Bottleneck</p>
        <SectionHeading text="Microstructure Analysis Shouldn't Be a Manual Bottleneck" accentFrom={2} />

        <Reveal className="problem__grid">
          {PROBLEMS.map((p, i) => (
            <SlideUp key={p.code} index={i}>
              <Card className="problem__card">
                <Icon name={p.icon} size="md" />
                <span className="problem__code mono">{p.code}</span>
                <h3>{p.title}</h3>
                <p>{p.desc}</p>
              </Card>
            </SlideUp>
          ))}
        </Reveal>

        <p className="problem__closing">
          NODIQ-X brings analysis, validation and reporting into one intelligent workflow.
        </p>
      </div>
    </section>
  );
}
