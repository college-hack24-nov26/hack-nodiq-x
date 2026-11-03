import { useState, useEffect } from 'react';
import Button from '../common/Button';
import { useAuth } from '../../context/AuthContext';
import {
  loginWithEmail,
  saveRememberedCredentials,
  getRememberedEmail,
} from '../../services/authService';
import './LoginForm.css';

export default function LoginForm({ onSubmit }) {
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [rememberMe, setRememberMe] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  // Pre-fill remembered email on mount (passwords are never stored)
  useEffect(() => {
    const rememberedEmail = getRememberedEmail();
    if (rememberedEmail) {
      setEmail(rememberedEmail);
      setRememberMe(true);
    }
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    try {
      const user = await loginWithEmail(email, password);

      if (rememberMe) {
        saveRememberedCredentials(email);
      }

      login(user);
      onSubmit?.({ email, user });
    } catch (err) {
      setError(err.message || 'Login failed. Please check your credentials.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <form className="login-form" onSubmit={handleSubmit}>
      <label className="login-form__field">
        <span className="login-form__label">Email</span>
        <input
          type="email"
          placeholder="you@company.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          disabled={isLoading}
        />
      </label>

      <label className="login-form__field">
        <div className="login-form__label-row">
          <span className="login-form__label">Password</span>
          <a href="/forgot-password" className="login-form__forgot">
            Forgot password
          </a>
        </div>
        <div className="login-form__password-wrapper">
          <input
            type={showPassword ? 'text' : 'password'}
            placeholder="••••••••"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            disabled={isLoading}
          />
          <button
            type="button"
            className="login-form__password-toggle"
            onClick={() => setShowPassword(!showPassword)}
            disabled={isLoading}
            aria-label={showPassword ? 'Hide password' : 'Show password'}
          >
            <span className="material-symbols-outlined">
              {showPassword ? 'visibility_off' : 'visibility'}
            </span>
          </button>
        </div>
      </label>

      <label className="login-form__remember">
        <input
          type="checkbox"
          checked={rememberMe}
          onChange={(e) => setRememberMe(e.target.checked)}
          disabled={isLoading}
        />
        <span className="login-form__label">Remember me</span>
      </label>

      {error && <div className="login-form__error">{error}</div>}

      <Button type="submit" size="lg" className="login-form__submit" disabled={isLoading}>
        {isLoading ? 'Logging in...' : 'Login'}
      </Button>
    </form>
  );
}
