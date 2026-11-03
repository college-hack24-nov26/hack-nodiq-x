import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import AuthVisual from '../components/auth/AuthVisual';
import OTPVerification from '../components/auth/OTPVerification';
import { verifyFirebaseIdToken } from '../services/authService';
import { useAuth } from '../context/AuthContext';
import './LoginPage.css';

export default function VerifyOtpPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login } = useAuth();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const { confirmationResult, phone } = location.state || {};

  const handleVerify = async (otp) => {
    if (!confirmationResult) {
      setError('Session expired. Please try logging in again.');
      return;
    }
    
    setLoading(true);
    setError('');
    
    try {
      const result = await confirmationResult.confirm(otp);
      const idToken = await result.user.getIdToken();
      const user = await verifyFirebaseIdToken(idToken);
      login(user);
      navigate('/dashboard');
    } catch (err) {
      console.error('OTP Error:', err);
      const friendly = {
        'auth/invalid-verification-code': 'That code is not valid. Check the SMS and try again.',
        'auth/code-expired': 'That code has expired. Go back and request a new OTP.',
        'auth/too-many-requests': 'Too many attempts. Please wait a few minutes before retrying.',
        'auth/network-request-failed': 'Network error — check your connection and retry.',
      }[err?.code];
      setError(friendly || err?.message || 'Invalid code. Please try again.');
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <AuthVisual />
      <div className="login-page__right">
        <div className="login-card">
          <h2>Verify your number</h2>
          <OTPVerification
            destination={phone || '+91 ••••• •••••'}
            onSubmit={handleVerify}
            onResend={() => navigate('/login')}
          />
          {error && <div style={{ color: '#ff4d4f', marginTop: '12px', fontSize: '0.9rem' }}>{error}</div>}
          {loading && <div style={{ marginTop: '12px', fontSize: '0.9rem', color: '#888' }}>Verifying...</div>}
        </div>
      </div>
    </div>
  );
}
