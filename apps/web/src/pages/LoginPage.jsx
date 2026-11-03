import { useState } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import AuthVisual from '../components/auth/AuthVisual';
import LavaParticles from '../components/auth/LavaParticles';
import GoogleLogin from '../components/auth/GoogleLogin';
import PhoneLogin from '../components/auth/PhoneLogin';
import LoginForm from '../components/auth/LoginForm';
import { useAuth } from '../context/AuthContext';
import { signInWithGoogle } from '../services/authService';
import './LoginPage.css';

const easeOut = [0.16, 1, 0.3, 1];

export default function LoginPage() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [googleError, setGoogleError] = useState('');

  const handleGoogleLogin = async () => {
    setGoogleError('');
    try {
      const user = await signInWithGoogle();
      login(user);
      navigate('/dashboard');
    } catch (err) {
      console.error(err);
      setGoogleError(err.message || 'Google login failed.');
    }
  };

  return (
    <div className="login-page">
      <div className="login-page__background">
        <AuthVisual />
        <LavaParticles />
      </div>

      <div className="login-page__content">
        <motion.button
          className="login-page__back-btn"
          onClick={() => navigate('/')}
          initial={{ opacity: 0, y: -12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.08, ease: easeOut }}
          whileHover={{ x: -2 }}
          whileTap={{ scale: 0.98 }}
        >
          ← Back to Home
        </motion.button>

        <motion.div
          className="login-card"
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.1, ease: easeOut }}
        >
          <motion.h2
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.2, ease: easeOut }}
          >
            Welcome back
          </motion.h2>

          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.28, ease: easeOut }}
          >
            <GoogleLogin onClick={handleGoogleLogin} />
            {googleError && <div style={{color: '#ff4d4f', fontSize: '0.8rem', marginTop: '8px', textAlign: 'center'}}>{googleError}</div>}
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.34, ease: easeOut }}
          >
            <PhoneLogin onSubmit={(confirmationResult, phone) => navigate('/verify-otp', { state: { confirmationResult, phone } })} />
          </motion.div>

          <motion.div
            className="login-card__divider"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.4, delay: 0.4 }}
          >
            <span />
            <span className="login-page__divider">OR</span>
            <span />
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.46, ease: easeOut }}
          >
            <LoginForm onSubmit={() => navigate('/home')} />
          </motion.div>

          <motion.p
            className="login-card__footer"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.5, delay: 0.55 }}
          >
            New to NODIQ-X? <a href="/signup">Create account</a>
          </motion.p>
        </motion.div>
      </div>
    </div>
  );
}
