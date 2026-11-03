import Reveal from '../animations/Reveal';
import SlideUp from '../animations/SlideUp';
import './Testimonials.css';
import SectionHeading from '../common/SectionHeading';

const NEEDS = [
  'Engineers need results they can inspect, not just a verdict.',
  'Every workflow should leave room for a human to check the AI\'s work.',
  'Reporting should take minutes, not a second round of manual work.',
];

export default function Testimonials() {
  return (
    <section className="section testimonials">
      <div className="container">
        <p className="eyebrow">Designed Around Real Engineering Workflows</p>
        <SectionHeading text="Built From What Engineers Actually Need" accentFrom={2} />

        <Reveal className="testimonials__grid">
          {NEEDS.map((n, i) => (
            <SlideUp key={n} index={i} className="testimonials__item">
              <span className="testimonials__quote-mark">&rdquo;</span>
              <p>{n}</p>
            </SlideUp>
          ))}
        </Reveal>
      </div>
    </section>
  );
}
