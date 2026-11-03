import { useRef, useState } from 'react';
import Button from '../common/Button';
import './OTPVerification.css';

const LENGTH = 6;

export default function OTPVerification({ destination = 'your device', onSubmit, onResend }) {
  const [digits, setDigits] = useState(Array(LENGTH).fill(''));
  const inputsRef = useRef([]);

  const handleChange = (i, value) => {
    if (!/^\d?$/.test(value)) return;
    const next = [...digits];
    next[i] = value;
    setDigits(next);
    if (value && i < LENGTH - 1) inputsRef.current[i + 1]?.focus();
  };

  const handleKeyDown = (i, e) => {
    if (e.key === 'Backspace' && !digits[i] && i > 0) {
      inputsRef.current[i - 1]?.focus();
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    onSubmit?.(digits.join(''));
  };

  return (
    <form className="otp" onSubmit={handleSubmit}>
      <p className="otp__hint">
        Enter the 6-digit code sent to <span className="mono">{destination}</span>
      </p>

      <div className="otp__boxes">
        {digits.map((d, i) => (
          <input
            key={i}
            ref={(el) => (inputsRef.current[i] = el)}
            className="otp__box mono"
            type="text"
            inputMode="numeric"
            maxLength={1}
            value={d}
            onChange={(e) => handleChange(i, e.target.value)}
            onKeyDown={(e) => handleKeyDown(i, e)}
          />
        ))}
      </div>

      <Button type="submit" size="lg" className="otp__submit">Verify</Button>

      <button type="button" className="otp__resend" onClick={onResend}>
        Didn't get a code? <span>Resend</span>
      </button>
    </form>
  );
}
