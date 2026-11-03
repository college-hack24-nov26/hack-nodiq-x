import { useEffect, useRef, useState } from 'react';
import { RecaptchaVerifier, signInWithPhoneNumber } from 'firebase/auth';
import { auth } from '../../firebase';
import './PhoneLogin.css';

/** Normalize any user input to E.164 (+91XXXXXXXXXX) for Firebase.
 * Strips spaces/dashes/brackets, drops a leading 0 or 91/+91/011 so
 * `+91 09876...`, `+919876...`, `09876...` all become +919876543210. */
function normalizeIndianMobile(raw) {
  let digits = String(raw).replace(/[^\d]/g, '');
  // strip up to one leading 0 (trunk prefix) and/or leading 91 country code
  digits = digits.replace(/^0+/, '');
  if (digits.startsWith('91') && digits.length > 10) digits = digits.slice(2);
  if (digits.length !== 10 || !/^[6-9]/.test(digits)) return null;
  return '+91' + digits;
}

/* Translate cryptic Firebase auth codes into actionable guidance. */
const FIREBASE_ERROR_MESSAGES = {
  'auth/invalid-phone-number':
    'Enter a valid 10-digit Indian mobile number (starting 6-9).',
  'auth/billing-not-enabled':
    'Phone sign-in needs the Firebase project on the Blaze (pay-as-you-go) plan to send real SMS. Ask the administrator to enable billing in Firebase Console — or use email login for now.',
  'auth/operation-not-allowed':
    'SMS sign-in is not enabled for this region yet. Please use email login, or ask the administrator to enable Phone provider and the India SMS region in Firebase Console.',
  'auth/too-many-requests':
    'Too many OTP requests from this device/network. Please wait a few minutes and try again.',
  'auth/quota-exceeded':
    'The SMS quota for this project is exhausted for today. Please try again later or use email login.',
  'auth/captcha-check-failed':
    'The security check (reCAPTCHA) failed or expired. Please retry — a fresh check will load automatically.',
  'auth/network-request-failed':
    'Network error while contacting the SMS service. Check your connection and retry.',
  'auth/user-disabled':
    'This account has been disabled. Contact the administrator.',
};

export default function PhoneLogin({ onSubmit }) {
  const [phone, setPhone] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const verifierRef = useRef(null);

  useEffect(() => {
    // Create the verifier once per mount; StrictMode double-mounts would
    // otherwise leak/invalidate the shared window singleton.
    if (!window.recaptchaVerifier && auth) {
      window.recaptchaVerifier = new RecaptchaVerifier(auth, 'recaptcha-container', {
        size: 'invisible',
      });
      verifierRef.current = window.recaptchaVerifier;
    }
    return () => {
      // Unmount (incl. StrictMode's double-invoke): clear the instance so the
      // next mount builds a fresh verifier against the live container node.
      if (verifierRef.current) {
        try { verifierRef.current.clear(); } catch { /* already cleared */ }
        if (window.recaptchaVerifier === verifierRef.current) {
          window.recaptchaVerifier = null;
        }
        verifierRef.current = null;
      }
    };
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    const fullPhone = normalizeIndianMobile(phone);
    if (!fullPhone) {
      setError(FIREBASE_ERROR_MESSAGES['auth/invalid-phone-number']);
      return;
    }
    setLoading(true);
    try {
      const appVerifier = window.recaptchaVerifier;
      if (!appVerifier) throw { code: 'auth/captcha-check-failed' };
      const confirmationResult = await signInWithPhoneNumber(auth, fullPhone, appVerifier);
      onSubmit?.(confirmationResult, fullPhone);
    } catch (err) {
      console.error(err);
      const friendly = err?.code && FIREBASE_ERROR_MESSAGES[err.code];
      setError(friendly || err?.message || 'Failed to send OTP. Try again.');
      setLoading(false);
    }
  };

  return (
    <form className="phone-login" onSubmit={handleSubmit}>
      <div id="recaptcha-container"></div>
      <div className="phone-login__field">
        <span className="phone-login__prefix mono">+91</span>
        <input
          type="tel"
          placeholder="Phone number"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          disabled={loading}
          required
        />
      </div>
      {error && <div style={{color: '#ff4d4f', fontSize: '0.8rem', marginTop: '8px', marginBottom: '8px'}}>{error}</div>}
      <button type="submit" className="phone-login__submit" disabled={loading}>
        {loading ? 'Sending OTP...' : 'Continue with Phone'}
      </button>
    </form>
  );
}
