import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import AuthVisual from '../components/auth/AuthVisual';
import { api } from '../services/api';
import './ResetPasswordPage.css';

const easeOut = [0.16, 1, 0.3, 1];

/**
 * ResetPasswordPage — two modes:
 *   /forgot-password          request a reset link by email
 *   /reset-password?token=…   set a new password (link from the email)
 * When SMTP is not configured the API returns the token directly, so the
 * page can link straight through (dev convenience, still single-use).
 */
export default function ResetPasswordPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = params.get('token') || '';

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const requestReset = async (e) => {
    e.preventDefault();
    setError(''); setMessage(''); setBusy(true);
    try {
      // Security: the API never returns the reset token in the response —
      // it travels only by email. The reply is intentionally generic.
      await api.forgotPassword(email);
      setMessage(`If ${email} has an account, a reset link is on its way.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const doReset = async (e) => {
    e.preventDefault();
    setError(''); setMessage(''); setBusy(true);
    try {
      await api.resetPassword({ token, password });
      setMessage('Password updated. You can sign in now.');
      setTimeout(() => navigate('/login', { replace: true }), 1200);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="reset-page">
      <div className="reset-page__background">
        <AuthVisual hideContent={true} />
      </div>

      <motion.div
        className="reset-card"
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.1, ease: easeOut }}
      >
        <motion.h2
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.2, ease: easeOut }}
        >
          {token ? 'Set a new password' : 'Reset your password'}
        </motion.h2>

        {!token ? (
          <motion.form onSubmit={requestReset}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.28, ease: easeOut }}
          >
            <label className="reset-field">
              <span className="reset-field-label">EMAIL</span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                required
                disabled={busy}
              />
            </label>
            {message && <p className="reset-message">{message}</p>}
            {error && <p className="reset-error">{error}</p>}
            <button className="reset-submit" type="submit" disabled={busy}>
              {busy ? 'Sending…' : 'Send reset link'}
            </button>
            <p className="reset-alt">Remembered it? <a href="/login">Sign in</a></p>
          </motion.form>
        ) : (
          <motion.form onSubmit={doReset}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.28, ease: easeOut }}
          >
            <label className="reset-field">
              <span className="reset-field-label">NEW PASSWORD</span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                minLength={6}
                required
                disabled={busy}
              />
            </label>
            {message && <p className="reset-message">{message}</p>}
            {error && <p className="reset-error">{error}</p>}
            <button className="reset-submit" type="submit" disabled={busy}>
              {busy ? 'Updating…' : 'Update password'}
            </button>
          </motion.form>
        )}
      </motion.div>
    </div>
  );
}
