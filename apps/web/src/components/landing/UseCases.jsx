import { motion } from 'framer-motion';
import Reveal from '../animations/Reveal';
import Card from '../common/Card';
import Icon from '../common/Icon';
import './UseCases.css';
import SectionHeading from '../common/SectionHeading';

const CASES = [
  { title: 'Metallurgical Engineers', desc: 'Analyze microstructure faster.', icon: 'engineer' },
  { title: 'Quality Engineers', desc: 'Monitor quality and identify anomalies.', icon: 'quality' },
  { title: 'Foundries & Manufacturers', desc: 'Support production quality workflows.', icon: 'manufacturing' },
  { title: 'Research Laboratories', desc: 'Accelerate materials research.', icon: 'research' },
];

const containerVariants = {
  hidden: {},
  show: {
    transition: {
      staggerChildren: 0.1,
      delayChildren: 0.1,
    },
  },
};

const cardVariants = {
  hidden: { 
    opacity: 0, 
    y: 20,
    rotateY: -10,
  },
  show: { 
    opacity: 1, 
    y: 0,
    rotateY: 0,
    transition: { 
      duration: 0.6, 
      ease: [0.16, 1, 0.3, 1]
    } 
  },
};

export default function UseCases() {
  return (
    <section className="section usecases" id="solutions">
      <div className="container">
        <Reveal>
          <p className="eyebrow">Who It's For</p>
        <SectionHeading text="Built for Modern Materials Analysis" accentFrom={2} />
        </Reveal>

        <motion.div 
          className="usecases__grid"
          initial="hidden"
          whileInView="show"
          viewport={{ once: true, amount: 0.2 }}
          variants={containerVariants}
        >
          {CASES.map((c) => (
            <motion.div
              key={c.title}
              variants={cardVariants}
              whileHover={{ y: -8 }}
            >
              <Card className="usecases__card" hoverable={false}>
                <Icon name={c.icon} size="md" />
                <h3>{c.title}</h3>
                <p>{c.desc}</p>
              </Card>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}
