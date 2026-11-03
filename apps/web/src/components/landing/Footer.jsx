import './Footer.css';

const COLUMNS = [
  {
    title: 'Product',
    links: [
      { label: 'Features', href: '#features' },
      { label: 'How It Works', href: '#how-it-works' },
      { label: 'Solutions', href: '#solutions' },
    ],
  },
  {
    title: 'Resources',
    links: [
      { label: 'Library', href: '#trust' },
      { label: 'Reports', href: '/reports' },
      { label: 'FAQ', href: '#faq' },
    ],
  },
  {
    title: 'Company',
    links: [
      { label: 'About', href: '#trust' },
      { label: 'Contact', href: '#contact' },
    ],
  },
  {
    title: 'Connect',
    links: [
      { label: 'GitHub', href: 'https://github.com/PixelCrafter-ath', external: true },
      { label: 'LinkedIn', href: 'https://www.linkedin.com/', external: true },
      { label: 'Email', href: 'mailto:atharvarandive28@gmail.com' },
    ],
  },
  {
    title: 'Legal',
    links: [
      { label: 'Privacy', href: '/privacy' },
      { label: 'Terms', href: '/terms' },
    ],
  },
];

export default function Footer() {
  return (
    <footer className="footer">
      <div className="container">
        <div className="footer__top">
          <div className="footer__brand">
            <span className="footer__logo">
              <span className="footer__mark" /> NODIQ<span className="footer__logo-accent">-X</span>
            </span>
            <p>AI-powered metallographic microstructure analysis for engineers who need to trust the result.</p>
          </div>

          <div className="footer__columns">
            {COLUMNS.map((col) => (
              <div key={col.title} className="footer__col">
                <h3 className="footer__col-title mono">{col.title}</h3>
                <ul>
                  {col.links.map((l) => (
                    <li key={l.label}>
                      <a
                        href={l.href}
                        {...(l.external ? { target: '_blank', rel: 'noreferrer' } : {})}
                      >
                        {l.label}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>

        <div className="footer__bottom">
          <span>© 2026 NODIQ-X</span>
        </div>
      </div>
    </footer>
  );
}
