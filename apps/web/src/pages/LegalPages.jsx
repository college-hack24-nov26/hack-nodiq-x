import { Link } from 'react-router-dom';
import './LegalPages.css';

export function Privacy() {
  return (
    <main className="legal-page">
      <div className="container legal-page__inner">
        <p className="eyebrow">Legal</p>
        <h1>Privacy Policy</h1>
        <p className="legal-page__updated mono">Last updated: September 2026</p>

        <h2>What we collect</h2>
        <p>
          NODIQ-X runs locally on your own machine. Analyses, reports and settings are stored
          on your device in <code>server_data/</code> and are never uploaded anywhere. If you
          send feedback through the contact form, we receive only the name, email address and
          message you choose to include.
        </p>

        <h2>Feedback</h2>
        <p>
          Feedback submitted via the contact form is saved locally in
          <code> server_data/feedback.json</code> and, when SMTP settings are configured,
          delivered by email to the developer inbox. It is used solely to respond to your
          message and improve the product.
        </p>

        <h2>Third-party services</h2>
        <p>
          If you configure an AI provider (Gemini, or an OpenAI-compatible endpoint) in
          <code> .env</code>, analysis context is sent to that provider to answer Copilot
          questions. Without configuration, the deterministic local fallback is used and no
          data leaves your machine.
        </p>

        <h2>Contact</h2>
        <p>
          Questions about this policy: <a href="mailto:atharvarandive28@gmail.com">atharvarandive28@gmail.com</a>
        </p>

        <Link className="legal-page__back" to="/">← Back to home</Link>
      </div>
    </main>
  );
}

export function Terms() {
  return (
    <main className="legal-page">
      <div className="container legal-page__inner">
        <p className="eyebrow">Legal</p>
        <h1>Terms of Use</h1>
        <p className="legal-page__updated mono">Last updated: September 2026</p>

        <h2>Acceptance</h2>
        <p>
          By using NODIQ-X you agree to these terms. If you do not agree, do not use the
          software.
        </p>

        <h2>Engineering judgement</h2>
        <p>
          NODIQ-X provides AI-assisted measurements intended to support — never replace —
          professional metallurgical judgement. Acceptance decisions (e.g. nodularity
          thresholds) must always be verified against the applicable standard or your own
          specification. Results are only as good as the input images and calibration
          provided.
        </p>

        <h2>No warranty</h2>
        <p>
          The software is provided “as is”, without warranty of any kind. The author is not
          liable for any damages arising from its use in production or quality decisions.
        </p>

        <h2>Contact</h2>
        <p>
          Questions about these terms: <a href="mailto:atharvarandive28@gmail.com">atharvarandive28@gmail.com</a>
        </p>

        <Link className="legal-page__back" to="/">← Back to home</Link>
      </div>
    </main>
  );
}
