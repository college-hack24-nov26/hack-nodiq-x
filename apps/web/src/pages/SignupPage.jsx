import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import AuthVisual from '../components/auth/AuthVisual';
import SignupForm from '../components/auth/SignupForm';
import './SignupPage.css';

const easeOut = [0.16, 1, 0.3, 1];

export default function SignupPage() {
  const navigate = useNavigate();

  return (
    <div className="signup-page">
      <div className="signup-page__background">
        <AuthVisual hideContent={true} />
      </div>

      <div className="signup-page__left">
        <motion.div
          className="signup-page__left-content"
          initial={{ opacity: 0, x: -24 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.6, delay: 0.1, ease: easeOut }}
        >
          <h1>Join NODIQ-X Today</h1>
          <p>
            Create your account and turn metallographic images into measurable,
            explainable results — AI-assisted detection with engineer verification
            built in.
          </p>
          <div className="signup-page__left-features">
            <div className="signup-page__feature">
              <span className="signup-page__feature-icon">✓</span>
              <p>AI-Assisted Nodule Detection</p>
            </div>
            <div className="signup-page__feature">
              <span className="signup-page__feature-icon">✓</span>
              <p>Confidence-Aware Analysis</p>
            </div>
            <div className="signup-page__feature">
              <span className="signup-page__feature-icon">✓</span>
              <p>Human Verification &amp; Reporting</p>
            </div>
          </div>
        </motion.div>
      </div>

      <div className="signup-page__right">
        <motion.button
          className="signup-page__back-btn"
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
          className="signup-card"
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.1, ease: easeOut }}
        >
          <motion.h2
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.2, ease: easeOut }}
          >
            Create account
          </motion.h2>

          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.28, ease: easeOut }}
          >
            <SignupForm onSubmit={() => navigate('/login')} />
          </motion.div>

          <motion.p
            className="signup-card__footer"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.5, delay: 0.55 }}
          >
            Already have an account? <a href="/login">Login</a>
          </motion.p>
        </motion.div>
      </div>
    </div>
  );
}
