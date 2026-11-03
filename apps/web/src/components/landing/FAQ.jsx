import { useState, useMemo } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import Reveal from '../animations/Reveal';
import './FAQ.css';
import SectionHeading from '../common/SectionHeading';

const QA = [
  { q: 'What does NODIQ-X analyze?', a: 'NODIQ-X analyzes metallographic microstructure images, detecting nodules and evaluating nodularity and morphology.', category: 'general' },
  { q: 'What image formats are supported?', a: 'NODIQ-X accepts standard microscopy image formats used in metallographic imaging workflows.', category: 'general' },
  { q: 'Can I manually correct AI detections?', a: 'Yes. Every detection can be reviewed, accepted, rejected, or corrected by an engineer.', category: 'features' },
  { q: 'How does confidence scoring work?', a: 'Each detection is assigned a confidence value so you can quickly identify results that need closer review.', category: 'features' },
  { q: 'Can I analyze multiple samples?', a: 'Yes. NODIQ-X supports batch analytics across multiple samples in a single workflow.', category: 'features' },
  { q: 'Can I generate reports?', a: 'Yes. Engineering reports can be generated directly from your analysis and review results.', category: 'features' },
  { q: 'What is NODIQ Copilot?', a: 'NODIQ Copilot is an AI assistant that answers questions about your analysis, grounded in your actual results.', category: 'copilot' },
  { q: 'How is validation performed?', a: 'Validation combines confidence scoring, ground truth comparison, reference libraries, and human verification.', category: 'validation' },
];

const CATEGORIES = [
  { id: 'all', label: 'All' },
  { id: 'general', label: 'General' },
  { id: 'features', label: 'Features' },
  { id: 'copilot', label: 'Copilot' },
  { id: 'validation', label: 'Validation' },
];

export default function FAQ() {
  const [openIndex, setOpenIndex] = useState(0);
  const [activeCategory, setActiveCategory] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');

  const filteredQA = useMemo(() => {
    return QA.filter(item => {
      const matchesCategory = activeCategory === 'all' || item.category === activeCategory;
      const matchesSearch = item.q.toLowerCase().includes(searchQuery.toLowerCase()) ||
                           item.a.toLowerCase().includes(searchQuery.toLowerCase());
      return matchesCategory && matchesSearch;
    });
  }, [activeCategory, searchQuery]);

  return (
    <section className="section faq" id="faq">
      <div className="container faq__container">
        <Reveal>
          <p className="eyebrow">FAQ</p>
        <SectionHeading text="Frequently Asked Questions" accentFrom={2} />
        </Reveal>

        <Reveal className="faq__controls">
          <div className="faq__search-wrapper">
            <input
              type="text"
              className="faq__search"
              placeholder="Search questions..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            <span className="material-symbols-outlined faq__search-icon">search</span>
          </div>

          <div className="faq__tabs">
            {CATEGORIES.map(cat => (
              <button
                key={cat.id}
                className={`faq__tab ${activeCategory === cat.id ? 'faq__tab--active' : ''}`}
                onClick={() => setActiveCategory(cat.id)}
              >
                {cat.label}
              </button>
            ))}
          </div>
        </Reveal>

        <div className="faq__list">
          {filteredQA.length > 0 ? (
            filteredQA.map((item) => (
              <div key={item.q} className="faq__item">
                <button
                  className="faq__question"
                  onClick={() => setOpenIndex(openIndex === item.q ? null : item.q)}
                  aria-expanded={openIndex === item.q}
                >
                  <span>{item.q}</span>
                  <span className={`faq__icon ${openIndex === item.q ? 'faq__icon--open' : ''}`}>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <line x1="12" y1="5" x2="12" y2="19" />
                      <line x1="5" y1="12" x2="19" y2="12" />
                    </svg>
                  </span>
                </button>
                <AnimatePresence initial={false}>
                  {openIndex === item.q && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
                      className="faq__answer-wrap"
                    >
                      <p className="faq__answer">{item.a}</p>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            ))
          ) : (
            <div className="faq__empty">
              <p>No questions found. Try a different search or category.</p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
