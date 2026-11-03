import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import SpecularButton from '../common/SpecularButton';
import ThemeToggle from '../common/ThemeToggle';
import './Navbar.css';

const LINKS = [
  { label: 'Product', href: '#product' },
  { label: 'How It Works', href: '#how-it-works' },
  { label: 'Features', href: '#features' },
  { label: 'Solutions', href: '#solutions' },
  { label: 'About', href: '#trust' },
];

export default function Navbar() {
  const navigate = useNavigate();
  const [scrolled, setScrolled] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [activeSection, setActiveSection] = useState('');

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    window.addEventListener('scroll', onScroll);
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  /* Scroll-spy: highlight the nav link for the section currently in view
     (audit issue 15 — visible active/current state in the global navigation). */
  useEffect(() => {
    const sections = LINKS.map((l) => document.getElementById(l.href.slice(1))).filter(Boolean);
    if (sections.length === 0) return undefined;

    const pickActive = () => {
      const probe = window.scrollY + 140; // offset for the sticky navbar
      let current = '';
      for (const s of sections) {
        if (s.offsetTop <= probe) current = s.id;
      }
      // Clear once the footer is reached — no section is "current" there.
      const footer = document.querySelector('footer');
      const nearBottom =
        window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 120;
      setActiveSection(nearBottom || (footer && footer.getBoundingClientRect().top < 140) ? '' : current);
    };

    pickActive();
    window.addEventListener('scroll', pickActive, { passive: true });
    window.addEventListener('resize', pickActive);
    return () => {
      window.removeEventListener('scroll', pickActive);
      window.removeEventListener('resize', pickActive);
    };
  }, []);

  return (
    <motion.header
      className={`navbar ${scrolled ? 'navbar--elevated' : ''}`}
      initial={{ opacity: 0, y: -12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
    >
      <div className="container navbar__inner">
        <a href="/" className="navbar__logo">
          <img src="/nodiq-x-flame.png" alt="NODIQ-X" className="navbar__flame-logo" />
          <span className="navbar__text">
            NODIQ<span className="navbar__logo-accent">-X</span>
          </span>
        </a>

        <nav className="navbar__links" aria-label="Page sections">
          {LINKS.map((link) => {
            const isActive = activeSection === link.href.slice(1);
            return (
              <a
                key={link.label}
                href={link.href}
                className={`navbar__link ${isActive ? 'navbar__link--active' : ''}`}
                aria-current={isActive ? 'true' : undefined}
              >
                {link.label}
              </a>
            );
          })}
        </nav>

        <div className="navbar__actions">
          <ThemeToggle />
          <SpecularButton
            size="md"
            radius={14}
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
        </div>

        <button
          className="navbar__hamburger"
          onClick={() => setMenuOpen((v) => !v)}
          aria-label="Toggle menu"
          aria-expanded={menuOpen}
        >
          <span />
          <span />
          <span />
        </button>
      </div>

      {menuOpen && (
        <motion.div
          className="navbar__mobile"
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: 'auto' }}
          exit={{ opacity: 0, height: 0 }}
        >
          {LINKS.map((link) => (
            <a key={link.label} href={link.href} onClick={() => setMenuOpen(false)}>
              {link.label}
            </a>
          ))}
          <ThemeToggle className="theme-toggle--mobile" />
          <SpecularButton
            size="md"
            radius={14}
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
            className="navbar__mobile-cta"
            href="/login"
            onClick={(e) => {
              e.preventDefault();
              setMenuOpen(false);
              navigate('/login');
            }}
          >
            Get Started
          </SpecularButton>
        </motion.div>
      )}
    </motion.header>
  );
}
