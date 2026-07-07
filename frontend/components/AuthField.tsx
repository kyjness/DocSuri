'use client';

import { useRef, useState } from 'react';
import styles from './AuthForm.module.css';

// AuthField — labeled input shared by LoginForm/SignupForm. Email fields get a
// clear (✕) affordance and have the browser spellcheck/auto-capitalize turned
// off (those produce a misleading red squiggle on addresses). Password fields
// get a show/hide toggle instead of clear (the conventional pattern; reveals
// what was typed rather than wiping it).

type Props = {
  id: string;
  label: string;
  type: 'email' | 'password' | 'text';
  value: string;
  onChange: (value: string) => void;
  autoComplete: string;
  error?: string;
  testId: string;
};

export function AuthField({ id, label, type, value, onChange, autoComplete, error, testId }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [reveal, setReveal] = useState(false);
  const isPassword = type === 'password';
  const errorId = `${id}-error`;
  const inputType = isPassword ? (reveal ? 'text' : 'password') : type;

  return (
    <div className={styles.field}>
      <label className={styles.label} htmlFor={id}>
        {label}
      </label>
      <div className={styles.inputWrap}>
        <input
          ref={inputRef}
          id={id}
          className={styles.input}
          type={inputType}
          autoComplete={autoComplete}
          spellCheck={isPassword ? undefined : false}
          autoCapitalize={isPassword ? undefined : 'none'}
          autoCorrect={isPassword ? undefined : 'off'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          data-testid={testId}
        />
        {isPassword ? (
          <button
            type="button"
            className={styles.adornment}
            onClick={() => setReveal((v) => !v)}
            aria-label={reveal ? '비밀번호 숨기기' : '비밀번호 표시'}
            aria-pressed={reveal}
            data-testid={`${testId}-reveal`}
          >
            {reveal ? <EyeOffIcon /> : <EyeIcon />}
          </button>
        ) : (
          <button
            type="button"
            className={styles.adornment}
            onClick={() => {
              onChange('');
              inputRef.current?.focus();
            }}
            disabled={!value}
            aria-hidden={value ? undefined : true}
            aria-label={`${label} 지우기`}
            data-testid={`${testId}-clear`}
          >
            ✕
          </button>
        )}
      </div>
      {error ? (
        <p id={errorId} className={styles.fieldError} role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

// Inline icons (no external dependency); inherit the button's currentColor and
// are aria-hidden since the button itself carries the accessible label.
const iconProps = {
  width: 20,
  height: 20,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
};

function EyeIcon() {
  return (
    <svg {...iconProps}>
      <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function EyeOffIcon() {
  return (
    <svg {...iconProps}>
      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
      <line x1="1" y1="1" x2="23" y2="23" />
    </svg>
  );
}
