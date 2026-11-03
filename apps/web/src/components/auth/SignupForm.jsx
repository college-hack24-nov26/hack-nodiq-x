import { useState } from 'react';
import Button from '../common/Button';
import { useAuth } from '../../context/AuthContext';
import { registerUser, saveRememberedCredentials } from '../../services/authService';
import './SignupForm.css';

export default function SignupForm({ onSubmit }) {
  const { signup } = useAuth();
  const [formData, setFormData] = useState({
    name: '',
    phone: '',
    email: '',
    password: '',
  });

  const [rememberMe, setRememberMe] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: value,
    }));
  };

  const validateForm = () => {
    // Email validation
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(formData.email)) {
      throw new Error('Please enter a valid email address');
    }

    // Password validation - at least 6 characters
    if (formData.password.length < 6) {
      throw new Error('Password must be at least 6 characters long');
    }

    // Phone validation - basic check
    const phoneRegex = /^[\d\s\-+()]{10,}$/;
    if (!phoneRegex.test(formData.phone)) {
      throw new Error('Please enter a valid phone number');
    }

    // Name validation
    if (formData.name.trim().length < 2) {
      throw new Error('Name must be at least 2 characters long');
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    try {
      validateForm();

      // Create the account on the backend (returns + stores the session)
      const user = await registerUser({
        name: formData.name,
        phone: formData.phone,
        email: formData.email,
        password: formData.password,
      });

      if (rememberMe) {
        saveRememberedCredentials(formData.email);
      }

      signup(user);
      onSubmit?.(formData);
    } catch (err) {
      setError(err.message || 'Signup failed. Please try again.');
      setIsLoading(false);
    }
  };

  return (
    <form className="signup-form" onSubmit={handleSubmit}>
      <label className="signup-form__field">
        <span className="signup-form__label">Name</span>
        <input
          type="text"
          name="name"
          placeholder="Full name"
          value={formData.name}
          onChange={handleChange}
          required
          disabled={isLoading}
        />
      </label>

      <label className="signup-form__field">
        <span className="signup-form__label">Phone</span>
        <input
          type="tel"
          name="phone"            placeholder="+91 98765 43210"
          value={formData.phone}
          onChange={handleChange}
          required
          disabled={isLoading}
        />
      </label>

      <label className="signup-form__field">
        <span className="signup-form__label">Email</span>
        <input
          type="email"
          name="email"
          placeholder="you@company.com"
          value={formData.email}
          onChange={handleChange}
          required
          disabled={isLoading}
        />
      </label>

      <label className="signup-form__field">
        <span className="signup-form__label">Password</span>
        <div className="signup-form__password-wrapper">
          <input
            type={showPassword ? 'text' : 'password'}
            name="password"
            placeholder="••••••••"
            value={formData.password}
            onChange={handleChange}
            required
            disabled={isLoading}
          />
          <button
            type="button"
            className="signup-form__password-toggle"
            onClick={() => setShowPassword(!showPassword)}
            disabled={isLoading}
            aria-label={showPassword ? 'Hide password' : 'Show password'}
          >
            <span className="material-symbols-outlined">
              {showPassword ? 'visibility_off' : 'visibility'}
            </span>
          </button>
        </div>
        <span className="signup-form__hint">Minimum 6 characters</span>
      </label>

      <label className="signup-form__remember">
        <input
          type="checkbox"
          checked={rememberMe}
          onChange={(e) => setRememberMe(e.target.checked)}
          disabled={isLoading}
        />
        <span className="signup-form__label">Remember me</span>
      </label>

      {error && <div className="signup-form__error">{error}</div>}

      <Button type="submit" size="lg" className="signup-form__submit" disabled={isLoading}>
        {isLoading ? 'Creating account...' : 'Create Account'}
      </Button>
    </form>
  );
}
