import { useState } from 'react';
import Reveal from '../animations/Reveal';
import Button from '../common/Button';
import './Contact.css';
import SectionHeading from '../common/SectionHeading';

const EMAIL = 'atharvarandive28@gmail.com';
const GITHUB = 'https://github.com/PixelCrafter-ath';
const PHONE = '+91 9579260830';
const COLLEGE = 'D. Y. Patil College of Engineering and Technology, Kasba Bawda, Kolhapur, Maharashtra 416006';

/* Standard signifiers for contact cards (audit issue 19) */
const MapPinIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
    <circle cx="12" cy="10" r="3" />
  </svg>
);
const GitHubIcon = () => (
  <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <path d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.58.11.79-.25.79-.55 0-.27-.01-1.17-.02-2.12-3.2.7-3.88-1.36-3.88-1.36-.52-1.33-1.28-1.68-1.28-1.68-1.04-.71.08-.7.08-.7 1.15.08 1.76 1.19 1.76 1.19 1.03 1.76 2.7 1.25 3.36.96.1-.75.4-1.25.72-1.54-2.55-.29-5.24-1.28-5.24-5.68 0-1.26.45-2.28 1.19-3.09-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11.04 11.04 0 0 1 5.78 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.83 1.19 3.09 0 4.41-2.7 5.38-5.27 5.67.41.36.78 1.06.78 2.14 0 1.55-.01 2.79-.01 3.17 0 .31.21.67.8.55A11.51 11.51 0 0 0 23.5 12C23.5 5.65 18.35.5 12 .5z" />
  </svg>
);
const PhoneIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z" />
  </svg>
);
const MailIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
    <polyline points="22,6 12,13 2,6" />
  </svg>
);

export default function Contact() {
  const [form, setForm] = useState({ name: '', email: '', message: '' });
  const [status, setStatus] = useState('idle'); // idle | sending | ok | error
  const [note, setNote] = useState('');

  const update = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    if (!form.message.trim() || status === 'sending') return;
    setStatus('sending');
    setNote('');
    try {
      const resp = await fetch('/api/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      const body = await resp.json().catch(() => null);
      if (!resp.ok) throw new Error(body?.error || `Request failed (${resp.status})`);
      setStatus('ok');
      setNote(body?.emailed
        ? 'Thank you! Your feedback was sent and delivered by email.'
        : 'Thank you! Your feedback was received and saved.');
      setForm({ name: '', email: '', message: '' });
    } catch (err) {
      setStatus('error');
      setNote(err.message || 'Something went wrong. Please try again.');
    }
  };

  return (
    <section className="section contact" id="contact">
      <div className="container contact__container">
        <Reveal>
          <p className="eyebrow">Contact</p>
        <SectionHeading text="Get in Touch" accentFrom={2} />
          <p className="contact__intro">
            Questions about NODIQ-X, feedback on the analysis, or collaboration ideas —
            reach out directly or use the form. Every message gets through.
          </p>
        </Reveal>

        <div className="contact__grid">
          <Reveal className="contact__cards">
            <div className="contact__card">
              <span className="contact__icon" aria-hidden="true"><MapPinIcon /></span>
              <h3>Address</h3>
              <p>{COLLEGE}</p>
            </div>
            <div className="contact__card">
              <span className="contact__icon" aria-hidden="true"><PhoneIcon /></span>
              <h3>Phone</h3>
              <p><a href="tel:+919579260830" className="contact__link">{PHONE}</a></p>
            </div>
            <div className="contact__card">
              <span className="contact__icon" aria-hidden="true"><MailIcon /></span>
              <h3>Email</h3>
              <p>
                <a href={`mailto:${EMAIL}`} className="contact__link">{EMAIL}</a>
              </p>
            </div>
            <div className="contact__card">
              <span className="contact__icon" aria-hidden="true"><GitHubIcon /></span>
              <h3>GitHub</h3>
              <p>
                <a href={GITHUB} target="_blank" rel="noreferrer" className="contact__link">
                  github.com/PixelCrafter-ath
                </a>
              </p>
            </div>
          </Reveal>

          <Reveal className="contact__form-wrap">
            <form className="contact__form" onSubmit={submit}>
              <h3>Send Feedback</h3>
              <p className="contact__form-hint">
                Feedback goes straight to the developer's inbox — no account needed.
              </p>
              <label>
                <span className="contact__label">NAME</span>
                <input
                  type="text"
                  value={form.name}
                  onChange={update('name')}
                  placeholder="Your name (optional)"
                  maxLength={120}
                />
              </label>
              <label>
                <span className="contact__label">EMAIL</span>
                <input
                  type="email"
                  value={form.email}
                  onChange={update('email')}
                  placeholder="you@example.com (optional)"
                  maxLength={200}
                />
              </label>
              <label>
                <span className="contact__label">MESSAGE *</span>
                <textarea
                  rows={5}
                  required
                  value={form.message}
                  onChange={update('message')}
                  placeholder="Tell us what you think — bugs, ideas, questions…"
                  maxLength={5000}
                />
              </label>
              <Button type="submit" className="contact__submit" disabled={status === 'sending' || !form.message.trim()}>
                {status === 'sending' ? 'Sending…' : 'Send Feedback'}
              </Button>
              {status === 'ok' && <p className="contact__note contact__note--ok">{note}</p>}
              {status === 'error' && <p className="contact__note contact__note--err">{note}</p>}
            </form>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
